import io
import shutil

import pytest
from PIL import Image

from paperless_ai_extract.adapters.address_ocr import TesseractAddressReader
from paperless_ai_extract.adapters.rendering import PopplerPillowRenderer
from paperless_ai_extract.adapters.sqlite_state import SqliteStateStore
from paperless_ai_extract.config import AddressWindowConfig
from paperless_ai_extract.domain.errors import UnsupportedInput


def test_state_roundtrip(tmp_path):
    state = SqliteStateStore(tmp_path / "s.db")
    state.store(1, "src", "fp", {"a": 1}, {})
    assert state.cached(1, "src", "fp") == {"a": 1} and state.cached(1, "src", "other") is None
    assert not state.has_succeeded(1)
    assert state.failure(1, "err", retry_delay=0) == 1
    state.success(1)
    assert state.has_succeeded(1) and state.retry_due(1)
    state.save_proposal(1, [{"field": "title"}])
    assert state.proposal(1) == [{"field": "title"}]
    state.drop_proposal(1)
    assert state.proposal(1) is None


def test_failure_backoff(tmp_path):
    state = SqliteStateStore(tmp_path / "s.db")
    state.failure(2, "e", retry_delay=1000)
    assert not state.retry_due(2)
    state.reset_attempts(2)
    assert state.retry_due(2)


def _png(width, height):
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def test_image_is_resized_to_longest_edge():
    [page] = PopplerPillowRenderer().render(_png(2000, 1000), "image/png", 1, 1120)
    assert Image.open(io.BytesIO(page)).size == (1120, 560)


def test_unsupported_type():
    with pytest.raises(UnsupportedInput):
        PopplerPillowRenderer().render(b"text", "text/plain", 1, 1120)


def _pdf():
    buffer = io.BytesIO()
    Image.new("RGB", (850, 1100), "white").save(buffer, format="PDF")
    return buffer.getvalue()


@pytest.mark.skipif(shutil.which("pdftoppm") is None, reason="poppler not installed")
def test_pdf_is_rendered():
    [page] = PopplerPillowRenderer().render(_pdf(), "application/pdf", 1, 1120)
    assert max(Image.open(io.BytesIO(page)).size) == 1120


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract not installed")
def test_address_reader_returns_one_reading_per_mode():
    readings = TesseractAddressReader(AddressWindowConfig(enabled=True, languages="eng")).read(_pdf())
    assert readings is not None and len(readings) == 2


def test_address_reader_rejects_non_pdf():
    assert TesseractAddressReader(AddressWindowConfig(enabled=True)).read(b"PNG") is None
