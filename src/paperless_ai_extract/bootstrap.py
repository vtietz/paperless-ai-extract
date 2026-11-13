"""Composition root: the only place that knows concrete adapters."""
from __future__ import annotations

from .adapters.address_ocr import NoAddressReader, TesseractAddressReader
from .adapters.date_ocr import TesseractDateReader
from .adapters.llm import create_llm_client
from .adapters.paperless import PaperlessClient
from .adapters.rendering import PopplerPillowRenderer
from .adapters.sqlite_state import SqliteStateStore
from .application.use_cases import MetadataExtractor
from .application.worker import QueueWorker
from .config import Config


def build_extractor(config: Config) -> MetadataExtractor:
    window = config.extraction.recipient.address_window
    return MetadataExtractor(
        config=config,
        store=PaperlessClient(config.paperless),
        llm=create_llm_client(config.llm),
        renderer=PopplerPillowRenderer(),
        address_reader=TesseractAddressReader(window) if window.enabled else NoAddressReader(),
        state=SqliteStateStore(config.state.path),
        date_reader=TesseractDateReader(),
    )


def build_worker(config: Config) -> QueueWorker:
    return QueueWorker(build_extractor(config), config.queue, config.state.heartbeat_file)
