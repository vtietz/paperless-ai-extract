from paperless_ai_extract.application.worker import QueueWorker
from paperless_ai_extract.domain.errors import LLMError

from conftest import TAGS, FakeLLM, answer, letter_doc


def test_cycle_processes_pending_documents(build, config):
    extractor, store = build([letter_doc(1), letter_doc(2, tags=[])], FakeLLM(answer()))
    worker = QueueWorker(extractor, config.queue)
    assert worker.cycle() == 1
    assert store.docs[1].title != "scan_0001" and store.docs[2].title == "scan_0001"


def test_apply_waits_until_analysis_is_done(build, config):
    doc = letter_doc(tags=[TAGS["pending"], TAGS["apply"]])
    extractor, store = build([doc], FakeLLM(answer()))
    worker = QueueWorker(extractor, config.queue)
    worker.cycle()                                   # analyses; apply skipped this cycle
    assert TAGS["apply"] in store.docs[1].tags
    worker.cycle()                                   # now applies (nothing stored -> removed)
    assert TAGS["apply"] not in store.docs[1].tags


def test_retry_backoff_keeps_document_queued(build, config):
    extractor, store = build([letter_doc()], FakeLLM(LLMError("down")))
    worker = QueueWorker(extractor, config.queue)
    worker.cycle()
    assert TAGS["pending"] in store.docs[1].tags
    assert not extractor.state.retry_due(1)          # waits for retry_delay
    assert worker.cycle() == 0


def test_run_once_writes_heartbeat(build, config, tmp_path):
    extractor, _ = build([], FakeLLM(answer()))
    beat = tmp_path / "beat"
    QueueWorker(extractor, config.queue, beat).run(once=True, install_signals=False)
    assert float(beat.read_text()) > 0


def test_missing_queue_tags_fail_the_cycle_not_the_process(build, config, taxonomy):
    taxonomy.tags.clear()
    extractor, _ = build([letter_doc()], FakeLLM(answer()))
    QueueWorker(extractor, config.queue).run(once=True, install_signals=False)
