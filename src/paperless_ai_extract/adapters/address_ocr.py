"""Tesseract reading of a conventional address window (portrait PDFs only)."""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

from ..config import AddressWindowConfig


class TesseractAddressReader:
    def __init__(self, config: AddressWindowConfig):
        self.config = config

    def read(self, pdf: bytes) -> list[str] | None:
        """One reading per configured page-segmentation mode; None if unsuitable."""
        config = self.config
        if pdf[:5] != b"%PDF-":
            return None
        env = dict(os.environ, OMP_THREAD_LIMIT="1", LC_ALL="C")
        try:
            with tempfile.TemporaryDirectory(prefix="pae-address-") as scratch:
                source = Path(scratch) / "document.pdf"
                source.write_bytes(pdf)
                info = subprocess.run(["pdfinfo", "-f", "1", "-l", "1", str(source)],
                                      capture_output=True, text=True, check=True,
                                      timeout=10, env=env).stdout
                size = re.search(r"Page\s+(?:1\s+)?size:\s*([\d.]+)\s+x\s+([\d.]+)", info)
                if not size:
                    return None
                width, height = map(float, size.groups())
                if width <= 0 or not config.min_aspect <= height / width <= config.max_aspect:
                    return None
                target = Path(scratch) / "address"
                subprocess.run(
                    ["pdftoppm", "-f", "1", "-singlefile", "-scale-to", str(config.scale_to),
                     "-x", str(config.x), "-y", str(config.y),
                     "-W", str(config.width), "-H", str(config.height),
                     "-png", str(source), str(target)],
                    capture_output=True, check=True, timeout=30, env=env)
                readings = []
                for mode in config.psm_modes:
                    result = subprocess.run(
                        ["tesseract", str(target.with_suffix(".png")), "stdout",
                         "-l", config.languages, "--psm", str(mode)],
                        capture_output=True, text=True, check=True, timeout=30, env=env)
                    readings.append(result.stdout[:6000])
                return readings
        except (OSError, subprocess.SubprocessError, UnicodeError, ValueError):
            return None


class NoAddressReader:
    def read(self, pdf: bytes) -> list[str] | None:
        return None
