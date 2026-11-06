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
        for doc_id in ex.store.document_ids_with_tag(tags["apply"], self.queue.batch_size):
            if self.stopping:
                return done
            if tags["pending"] in ex.store.document(doc_id).tags:
                continue  # analyse first; apply on a later cycle
            try:
                ex.apply_proposal(doc_id, ctx)
                done += 1
            except StoreError as exc:
                log.warning("document %s: apply failed: %s", doc_id, exc)
        for doc_id in ex.store.document_ids_with_tag(tags["pending"], self.queue.batch_size):
            if self.stopping:
                return done
            if not ex.state.retry_due(doc_id):
                continue
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
