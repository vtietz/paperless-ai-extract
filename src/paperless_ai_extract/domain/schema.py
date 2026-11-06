"""Structured-output schema and strict parsing of the model's answer."""
from __future__ import annotations

import json

from ..config import ExtractionConfig
from .errors import ExtractionError
from .models import Extraction


def build_schema(config: ExtractionConfig, recipient_labels: list[str] | None) -> dict:
    """Property order matters to small models; it follows the validated pilot."""
    props: dict = {}
    if len(config.kinds) > 1:
        props["kind"] = {"type": "string", "enum": list(config.kinds)}
    if config.articles.enabled:
        props["authors"] = {"type": "array", "maxItems": 12,
                            "items": {"type": "string", "maxLength": 128}}
        props["publication_year"] = {"anyOf": [
            {"type": "integer", "minimum": 1000, "maximum": 2999}, {"type": "null"}]}
    props["title"] = {"type": "string", "maxLength": config.title_max_length}
    props["correspondents"] = {"type": "array", "maxItems": 1,
                               "items": {"type": "string", "maxLength": 128}}
    props["document_types"] = {"type": "array", "maxItems": 1,
                               "items": {"type": "string", "maxLength": 64}}
    if config.recipient.enabled:
        if not recipient_labels:
            raise ValueError("recipient extraction needs dropdown labels")
        props["addressee_text"] = {"type": "string", "maxLength": 240}
        props["recipient"] = {"type": "string", "enum": list(recipient_labels)}
    return {"type": "object", "additionalProperties": False,
            "properties": props, "required": list(props)}


def _strings(value, name: str, limit: int) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ExtractionError(f"{name} must be a list of strings")
    return [v.strip() for v in value if v.strip()][:limit]


def parse_extraction(text: str, config: ExtractionConfig,
                     recipient_labels: list[str] | None) -> Extraction:
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ExtractionError("model answer is not valid JSON") from exc
    if not isinstance(data, dict):
        raise ExtractionError("model answer is not a JSON object")

    kind = data.get("kind", config.kinds[0]) if len(config.kinds) > 1 else config.kinds[0]
    if kind not in config.kinds:
        raise ExtractionError(f"kind {kind!r} is not configured")
    title = data.get("title", "")
    if not isinstance(title, str):
        raise ExtractionError("title must be a string")
    correspondents = _strings(data.get("correspondents"), "correspondents", 1)
    types = _strings(data.get("document_types"), "document_types", 1)
    result = Extraction(
        kind=kind,
        title=" ".join(title.split())[: config.title_max_length],
        correspondent=correspondents[0] if correspondents else None,
        document_type=types[0] if types else None,
    )
    if config.articles.enabled:
        result.authors = _strings(data.get("authors"), "authors", 12)
        year = data.get("publication_year")
        if year is not None and (not isinstance(year, int) or isinstance(year, bool)
                                 or not 1000 <= year <= 2999):
            raise ExtractionError("publication_year must be a four-digit integer or null")
        result.publication_year = year
    if config.recipient.enabled:
        recipient = data.get("recipient")
        if recipient not in (recipient_labels or []):
            raise ExtractionError("recipient is not one of the configured dropdown labels")
        addressee = data.get("addressee_text", "")
        if not isinstance(addressee, str):
            raise ExtractionError("addressee_text must be a string")
        result.recipient = recipient
        result.addressee_text = addressee[:240]
    return result
