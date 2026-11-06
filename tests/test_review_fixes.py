"""Regression tests for the external review of 76676e5 (cases reproduced there)."""
import httpx

from paperless_ai_extract.adapters.paperless import PaperlessClient
from paperless_ai_extract.application.worker import QueueWorker
from paperless_ai_extract.config import ExtractionConfig, PaperlessConfig
from paperless_ai_extract.domain.errors import ExtractionError
from paperless_ai_extract.domain.evidence import date_supported, month_number

from conftest import TAGS, FakeLLM, answer, letter_doc


# 1 -- an old accept tag must not approve a new, unreviewed proposal
def test_old_apply_tag_does_not_authorize_new_proposal(build, config):
    llm = FakeLLM(answer(title="First proposal"))
    extractor, store = build([letter_doc(title="Manual title")], llm)
    extractor.process(1, extractor.context())
    store.docs[1].tags += [TAGS["apply"], TAGS["pending"]]
    llm.answers = [answer(title="Different unreviewed proposal")]
    store.checksum = lambda *_: "new-file-checksum"
    worker = QueueWorker(extractor, config.queue)
    worker.cycle()
    worker.cycle()
    assert store.docs[1].title == "Manual title"
    assert TAGS["apply"] not in store.docs[1].tags and TAGS["proposal"] in store.docs[1].tags
    store.docs[1].tags.append(TAGS["apply"])        # the user accepts the new proposal
    worker.cycle()
    assert store.docs[1].title == "Different unreviewed proposal"


def test_apply_tag_added_during_analysis_is_also_reset(build):
    extractor, store = build([letter_doc(title="Manual title")], FakeLLM(answer()))
    ctx = extractor.context()
    original = extractor.analyse

    def analyse_while_user_tags(*a, **kw):
        outcome = original(*a, **kw)
        store.docs[1].tags.append(TAGS["apply"])
        return outcome
    extractor.analyse = analyse_while_user_tags
    extractor.process(1, ctx)
    assert TAGS["apply"] not in store.docs[1].tags


# 2 -- the write guard re-reads after creating taxonomy (narrowed race window)
def test_edit_during_taxonomy_creation_is_preserved(build):
    from conftest import LETTER
    doc = letter_doc(content=LETTER + "\nNetzbetreiber Nord")
    extractor, store = build([doc], FakeLLM(answer(correspondents=["Netzbetreiber Nord"])))
    original = store.create_object

    def create_while_user_edits(endpoint, name):
        item = original(endpoint, name)
        store.docs[1].correspondent = 11              # user picked one meanwhile
        return item
    store.create_object = create_while_user_edits
    extractor.process(1, extractor.context())
    assert store.docs[1].correspondent == 11


# 3 -- incomplete answers are failures, not empty results
def test_empty_json_is_rejected_and_document_stays_queued(build, config):
    config.extraction = ExtractionConfig()
    extractor, store = build([letter_doc()], FakeLLM({}), cfg=config)
    worker = QueueWorker(extractor, config.queue)
    worker.cycle()
    assert TAGS["pending"] in store.docs[1].tags and not extractor.state.has_succeeded(1)
    assert extractor.state.cached(1, "x", "y") is None


def test_partial_json_names_missing_fields(config):
    import pytest
    from paperless_ai_extract.domain.schema import parse_extraction
    config.extraction = ExtractionConfig()
    with pytest.raises(ExtractionError, match="correspondents, document_types"):
        parse_extraction('{"title": "x"}', config.extraction, None)


# 4 -- textual dates must match the month
def test_textual_date_checks_month():
    assert not date_supported("2025-12-12", "12. März 2025")
    assert not date_supported("2025-01-12", "March 12, 2025")
    assert date_supported("2025-03-12", "12. März 2025")
    assert date_supported("2025-03-12", "March 12th, 2025")
    assert date_supported("2025-10-01", "1. Okt. 2025")
    assert month_number("Dez.") == 12 and month_number("Banana") is None


# 5 -- documents in backoff must not starve newer work
def test_backoff_does_not_starve_ready_documents(build, config):
    config.queue.batch_size = 1
    extractor, store = build([letter_doc(1), letter_doc(2)], FakeLLM(answer()))
    extractor.state.failure(1, "temporary", 3600)
    assert QueueWorker(extractor, config.queue).cycle() == 1
    assert extractor.state.has_succeeded(2) and TAGS["pending"] in store.docs[1].tags


def test_adapter_returns_all_queued_ids_across_pages():
    def handler(request):
        page = int(request.url.params["page"])
        return httpx.Response(200, json={"results": [{"id": page * 10}],
                                         "next": "x" if page < 3 else None})
    client = PaperlessClient(PaperlessConfig(url="http://p", token="t"), httpx.MockTransport(handler))
    assert client.document_ids_with_tag(5) == [10, 20, 30]
