"""Application use cases against in-memory fakes."""
import pytest

from paperless_ai_extract.domain.errors import LLMTimeout, UnsupportedInput

from conftest import JOINT, RECIPIENT_FIELD, TAGS, FakeAddressReader, FakeLLM, answer, letter_doc


def test_process_fills_tags_and_records_state(build):
    extractor, store = build([letter_doc()], FakeLLM(answer()))
    ctx = extractor.context()
    outcome = extractor.process(1, ctx)
    doc = store.docs[1]
    assert doc.title == "Jahresabrechnung Strom 2025" and doc.correspondent == 10
    assert doc.custom_fields[RECIPIENT_FIELD["id"]] == "opt-joint"
    assert TAGS["pending"] not in doc.tags and TAGS["proposal"] not in doc.tags
    assert not outcome.plan.proposals and 1 not in store.notes       # clean fill: no note
    assert extractor.state.has_succeeded(1)


def test_image_mode_sends_rendered_page_and_no_ocr(build):
    llm = FakeLLM(answer())
    extractor, _ = build([letter_doc()], llm)
    extractor.analyse(1, extractor.context())
    prompt, images, schema = llm.calls[0]
    assert images == [b"PNG-page"] and "BEGIN DOCUMENT OCR" not in prompt
    assert schema["properties"]["recipient"]["enum"][-1] == "Unassigned"


def test_text_mode_sends_ocr_without_images(build, config_factory):
    cfg = config_factory()
    cfg.input = cfg.input.model_copy(update={"mode": "text"})
    llm = FakeLLM(answer())
    extractor, _ = build([letter_doc()], llm, cfg=cfg)
    extractor.analyse(1, extractor.context())
    prompt, images, _ = llm.calls[0]
    assert images == [] and "Muster/Beispiel" in prompt.split("BEGIN DOCUMENT OCR")[1]


def test_text_mode_without_content_is_permanent_failure(build, config_factory):
    cfg = config_factory()
    cfg.input = cfg.input.model_copy(update={"mode": "text"})
    extractor, _ = build([letter_doc(content="  ")], FakeLLM(answer()), cfg=cfg)
    with pytest.raises(UnsupportedInput):
        extractor.analyse(1, extractor.context())


def test_extraction_is_cached_and_not_repeated(build):
    llm = FakeLLM(answer())
    extractor, _ = build([letter_doc()], llm)
    ctx = extractor.context()
    first = extractor.analyse(1, ctx)
    second = extractor.analyse(1, ctx)
    assert not first.cached and second.cached and len(llm.calls) == 1
    extractor.analyse(1, ctx, force=True)
    assert len(llm.calls) == 2


def test_analyse_never_writes(build):
    extractor, store = build([letter_doc()], FakeLLM(answer()))
    extractor.analyse(1, extractor.context())
    assert store.writes == [] and store.notes == {} and not extractor.state.has_succeeded(1)


def test_rerun_proposes_and_apply_accepts(build):
    extractor, store = build([letter_doc(title="Eigener Titel", correspondent=11)],
                             FakeLLM(answer()))
    ctx = extractor.context()
    extractor.process(1, ctx)                        # first run: fills empty fields only
    assert store.docs[1].title == "Eigener Titel"
    assert TAGS["proposal"] in store.docs[1].tags
    assert 'Title: "Eigener Titel" -> "Jahresabrechnung Strom 2025"' in store.notes[1][0]

    store.docs[1].tags.append(TAGS["apply"])
    written = extractor.apply_proposal(1, ctx)
    assert {c.field for c in written} == {"title", "correspondent"}
    assert store.docs[1].title == "Jahresabrechnung Strom 2025" and store.docs[1].correspondent == 10
    assert TAGS["apply"] not in store.docs[1].tags and TAGS["proposal"] not in store.docs[1].tags
    assert extractor.state.proposal(1) is None


def test_apply_skips_fields_edited_after_the_proposal(build):
    extractor, store = build([letter_doc(title="Eigener Titel", correspondent=11)],
                             FakeLLM(answer()))
    ctx = extractor.context()
    extractor.process(1, ctx)
    store.docs[1].title = "Von Hand korrigiert"
    written = extractor.apply_proposal(1, ctx)
    assert [c.field for c in written] == ["correspondent"]
    assert store.docs[1].title == "Von Hand korrigiert"
    assert "Skipped (field edited since the proposal): Title" in store.notes[1][-1]


def test_concurrent_edit_during_analysis_is_preserved(build):
    extractor, store = build([letter_doc()], FakeLLM(answer()))
    ctx = extractor.context()
    original = extractor.analyse

    def analyse_then_user_edits(*a, **kw):
        outcome = original(*a, **kw)
        store.docs[1].title = "User typed this meanwhile"
        return outcome
    extractor.analyse = analyse_then_user_edits
    extractor.process(1, ctx)
    assert store.docs[1].title == "User typed this meanwhile"


def test_unverified_recipient_flow(build):
    ans = answer(recipient="Kim Muster", addressee_text="Kim Muster")
    extractor, store = build([letter_doc()], FakeLLM(ans))
    ctx = extractor.context()
    extractor.process(1, ctx)
    assert store.docs[1].custom_fields[RECIPIENT_FIELD["id"]] == "opt-none"
    assert TAGS["review"] in store.docs[1].tags and TAGS["proposal"] in store.docs[1].tags
    extractor.apply_proposal(1, ctx)                  # user accepts the unverified choice
    assert store.docs[1].custom_fields[RECIPIENT_FIELD["id"]] == "opt-kim"


def test_address_reader_confirms_joint_recipient(build):
    from conftest import LETTER
    reader = FakeAddressReader([LETTER, LETTER])
    doc = letter_doc(content="Jahresabrechnung, Adresse unlesbar")
    extractor, store = build([doc], FakeLLM(answer(addressee_text="unlesbar")), reader)
    extractor.process(1, extractor.context())
    assert reader.calls == 1
    assert store.docs[1].custom_fields[RECIPIENT_FIELD["id"]] == "opt-joint"


def test_new_correspondent_created_unowned_on_fill(build):
    from conftest import LETTER
    doc = letter_doc(content=LETTER + "\nNetzbetreiber Nord")
    extractor, store = build([doc], FakeLLM(answer(correspondents=["Netzbetreiber Nord"])))
    extractor.config.taxonomy.new_correspondents = "create"
    extractor.process(1, extractor.context())
    assert ("create", "correspondents", "Netzbetreiber Nord") in store.writes
    assert store.docs[1].correspondent == store.next_id


def test_failure_retries_then_gives_up(build):
    extractor, store = build([letter_doc()], FakeLLM(LLMTimeout("slow")))
    ctx = extractor.context()
    for attempt in range(1, 4):
        with pytest.raises(LLMTimeout) as err:
            extractor.process(1, ctx)
        gave_up = extractor.record_failure(1, err.value, ctx)
        assert gave_up == (attempt == 3)
    assert TAGS["error"] in store.docs[1].tags and TAGS["pending"] not in store.docs[1].tags
    assert "gave up after 3 attempt(s)" in store.notes[1][-1]


def test_permanent_failure_gives_up_immediately(build):
    extractor, store = build([letter_doc()], FakeLLM(answer()))
    ctx = extractor.context()
    assert extractor.record_failure(1, UnsupportedInput("no pages"), ctx)
    assert TAGS["error"] in store.docs[1].tags


def test_missing_tags_are_created_only_when_allowed(build, taxonomy):
    taxonomy.tags.clear()
    extractor, store = build([letter_doc()], FakeLLM(answer()))
    assert extractor.context(create_tags=False).tag_ids == {}
    ids = extractor.context(create_tags=True).tag_ids
    assert set(ids) == {"pending", "apply", "proposal", "review", "error"}
    assert all(op[0] == "create" and op[1] == "tags" for op in store.writes)
