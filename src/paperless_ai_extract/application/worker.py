"""Tag-driven queue: `pending` -> analyse; `apply` -> accept stored proposal."""
from __future__ import annotations

import logging
import signal
import time
from pathlib import Path

from ..config import ConfigError, QueueConfig
from ..domain.errors import ExtractError, StoreError
from .use_cases import MetadataExtractor

log = logging.getLogger("paperless_ai_extract")


class QueueWorker:
    def __init__(self, extractor: MetadataExtractor, queue: QueueConfig,
                 heartbeat_file: Path | None = None, sleep=time.sleep):
        self.extractor = extractor
        self.queue = queue
        self.heartbeat_file = heartbeat_file
        self.sleep = sleep
        self.stopping = False

    def stop(self, *_):
        log.info("stop requested; finishing the current document")
        self.stopping = True

    def cycle(self) -> int:
        ex = self.extractor
        ctx = ex.context()
        tags = ctx.tag_ids
        if "pending" not in tags or "apply" not in tags:
            raise ConfigError("queue tags missing; run `check --create-tags` "
                              "or set queue.create_missing_tags")
        done = 0
        pending = ex.store.document_ids_with_tag(tags["pending"])
        # A document queued for re-analysis gets a new proposal; processing it
        # removes a stale accept tag instead of applying the old proposal.
        accepted = [d for d in ex.store.document_ids_with_tag(tags["apply"])
                    if d not in set(pending)]
        for doc_id in accepted[: self.queue.batch_size]:
            if self.stopping:
                return done
            try:
                ex.apply_proposal(doc_id, ctx)
                done += 1
            except StoreError as exc:
                log.warning("document %s: apply failed: %s", doc_id, exc)
        # Select eligible work before limiting, so documents in retry backoff
        # never block newer ones.
        due = [d for d in pending if ex.state.retry_due(d)]
        for doc_id in due[: self.queue.batch_size]:
            if self.stopping:
                return done
            try:
                ex.process(doc_id, ctx)
                done += 1
            except ExtractError as exc:
                try:
                    ex.record_failure(doc_id, exc, ctx)
                except StoreError as inner:
                    log.error("document %s: could not record failure: %s", doc_id, inner)
        return done

    def _heartbeat(self):
        if not self.heartbeat_file:
            return
        try:
            self.heartbeat_file.parent.mkdir(parents=True, exist_ok=True)
            self.heartbeat_file.write_text(str(time.time()))
        except OSError:
            log.warning("cannot write heartbeat %s", self.heartbeat_file)

    def run(self, once: bool = False, install_signals: bool = True):
        if install_signals:
            signal.signal(signal.SIGTERM, self.stop)
            signal.signal(signal.SIGINT, self.stop)
        while not self.stopping:
            try:
                done = self.cycle()
            except (StoreError, ConfigError) as exc:
                log.error("cycle failed: %s", exc)
                done = 0
            self._heartbeat()
            if once:
                return
            if done:
                continue  # more work may be queued
            waited = 0.0
            while not self.stopping and waited < self.queue.poll_interval:
                self.sleep(1)
                waited += 1
