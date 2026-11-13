import subprocess
from types import SimpleNamespace

import pytest
from paperless_ai_extract.adapters.date_ocr import TesseractDateReader


@pytest.mark.parametrize('text,expected', [
    (b'31. Juli 2023', True), (b'30. Juli 2023', False), (b'2023', False),
    (b'31.07.2022', False), (b'', False)])
def test_date_reader_requires_complete_matching_date(monkeypatch, text, expected):
    def run(command, **kwargs):
        assert command[:3] == ['tesseract', 'stdin', 'stdout']
        assert kwargs['input'] == b'image' and kwargs['timeout'] == 90
        return SimpleNamespace(stdout=text)
    monkeypatch.setattr(subprocess, 'run', run)
    assert TesseractDateReader().supports(b'image', '2023-07-31') is expected


def test_date_reader_failure_keeps_review(monkeypatch):
    def run(*args, **kwargs):
        raise subprocess.TimeoutExpired('tesseract', 90)
    monkeypatch.setattr(subprocess, 'run', run)
    assert not TesseractDateReader().supports(b'image', '2023-07-31')
