"""Turn a downloaded file into page images: Poppler for PDFs, Pillow for images."""
from __future__ import annotations

import io
import subprocess
import tempfile
from pathlib import Path

from ..domain.errors import UnsupportedInput


class PopplerPillowRenderer:
    def render(self, data: bytes, mime: str, pages: int, max_edge: int) -> list[bytes]:
        mime = (mime or "").split(";")[0].strip().lower()
        if mime == "application/pdf" or data[:5] == b"%PDF-":
            return self._pdf(data, pages, max_edge)
        if mime.startswith("image/"):
            return self._image(data, pages, max_edge)
        raise UnsupportedInput(f"cannot render {mime or 'unknown type'} as an image")

    @staticmethod
    def _pdf(data: bytes, pages: int, max_edge: int) -> list[bytes]:
        with tempfile.TemporaryDirectory(prefix="pae-render-") as scratch:
            source = Path(scratch) / "document.pdf"
            source.write_bytes(data)
            try:
                # -scale-to fits the longest edge, matching the validated pilot input.
                subprocess.run(
                    ["pdftoppm", "-f", "1", "-l", str(pages), "-scale-to", str(max_edge),
                     "-png", str(source), str(Path(scratch) / "page")],
                    capture_output=True, check=True, timeout=120)
            except (OSError, subprocess.SubprocessError) as exc:
                raise UnsupportedInput(f"PDF rendering failed: {exc.__class__.__name__}") from exc
            files = sorted(Path(scratch).glob("page*.png"))
            if not files:
                raise UnsupportedInput("PDF rendering produced no pages")
            return [f.read_bytes() for f in files]

    @staticmethod
    def _image(data: bytes, pages: int, max_edge: int) -> list[bytes]:
        from PIL import Image, ImageSequence
        try:
            image = Image.open(io.BytesIO(data))
            result = []
            for frame in ImageSequence.Iterator(image):
                page = frame.convert("RGB")
                page.thumbnail((max_edge, max_edge))
                buffer = io.BytesIO()
                page.save(buffer, format="PNG")
                result.append(buffer.getvalue())
                if len(result) >= pages:
                    break
            return result
        except (OSError, ValueError) as exc:
            raise UnsupportedInput(f"image decoding failed: {exc}") from exc
