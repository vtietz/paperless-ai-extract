"""Confirm an already selected issue date using independent high-resolution OCR."""
import subprocess

from ..domain.evidence import date_supported


class TesseractDateReader:
    def supports(self, image: bytes, iso_date: str) -> bool:
        try:
            result = subprocess.run(
                ['tesseract', 'stdin', 'stdout', '-l', 'deu+eng'],
                input=image, capture_output=True, check=True, timeout=90)
        except (OSError, subprocess.SubprocessError):
            return False
        return date_supported(iso_date, result.stdout.decode('utf-8', errors='replace'))
