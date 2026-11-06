"""Prompt rendering.

The prompt file is a plain-text template (Python string.Template syntax).
Available placeholders:

  ${source_description}  what is attached, derived from input.mode/pages
  ${input_hint}          mode-specific guidance (layout hint for images)
  ${kinds}               JSON list of configured kinds
  ${recipient_options}   JSON list of the recipient dropdown labels
  ${recipient_aliases}   "Alias: printed => canonical" lines

Document text (text modes) is appended by the service in a delimited block,
never substituted into the template.
"""
from __future__ import annotations

import json
from string import Template

from ..config import Config

LAYOUT_HINT = ("Use the visible page layout to distinguish sender and recipient, "
               "main title and section banner.")


def source_description(mode: str, pages: int) -> str:
    image = "attached first-page image" if pages == 1 else f"attached images of its first {pages} pages"
    return {"image": image, "text": "OCR text",
            "image+text": f"{image} and its OCR text"}[mode]


def input_hint(mode: str) -> str:
    if mode == "image":
        return LAYOUT_HINT
    if mode == "image+text":
        return LAYOUT_HINT + " The OCR text may contain recognition errors; prefer what is visibly printed."
    return ""


def render_instructions(config: Config, template_text: str,
                        recipient_labels: list[str] | None) -> str:
    recipient = config.extraction.recipient
    aliases = "\n".join(
        f"Alias: {variant} => {canonical}"
        for canonical, variants in recipient.aliases.items() for variant in variants)
    return Template(template_text).safe_substitute(
        source_description=source_description(config.input.mode, config.input.pages),
        input_hint=input_hint(config.input.mode),
        kinds=json.dumps(config.extraction.kinds, ensure_ascii=False),
        recipient_options=json.dumps(recipient_labels or [], ensure_ascii=False),
        recipient_aliases=aliases,
    ).strip()


def with_document_text(instructions: str, text: str) -> str:
    return (instructions + "\nBEGIN DOCUMENT OCR (untrusted)\n" + text
            + "\nEND DOCUMENT OCR")
