"""Structured-output schema and strict parsing of the model's answer."""
from __future__ import annotations

import json
from datetime import date

from ..config import ExtractionConfig
from .errors import ExtractionError
from .models import Extraction

DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"


def build_schema(config: ExtractionConfig, recipient_labels: list[str] | None,
                 tag_names: list[str] | None = None,
                 type_enum: list[str] | None = None) -> dict:
    """type_enum restricts document_types to existing names (creation disabled).

    Property order matters to small models; the household/article order follows
    the validated pilot, optional generic fields are inserted after document type."""
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
    type_item = ({"type": "string", "enum": list(type_enum)} if type_enum
                 else {"type": "string", "maxLength": 64})
    props["document_types"] = {"type": "array", "maxItems": 1, "items": type_item}
    if config.tags.enabled and tag_names:
        props["tags"] = {"type": "array", "maxItems": config.tags.max_tags,
                         "items": {"type": "string", "enum": list(tag_names)}}
    if config.document_date.enabled:
        props["document_date"] = {"anyOf": [
            {"type": "string", "pattern": DATE_PATTERN}, {"type": "null"}]}
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


def _iso_date(value) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip()).isoformat()
    except ValueError:
        return None


def parse_extraction(text: str, config: ExtractionConfig,
                     recipient_labels: list[str] | None,
                     tag_names: list[str] | None = None) -> Extraction:
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ExtractionError("model answer is not valid JSON") from exc
    if not isinstance(data, dict):
        raise ExtractionError("model answer is not a JSON object")
    # Backends without schema enforcement (json_object/none) may return partial
    # or empty objects; an answer without the required fields is a failure, not
    # an empty result that would silently complete the document.
    required = build_schema(config, recipient_labels, tag_names)["required"]
    missing = [key for key in required if key not in data]
    if missing:
        raise ExtractionError("model answer lacks required fields: " + ", ".join(missing))

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
    if config.tags.enabled:
        allowed = set(tag_names or [])
        # Servers without schema enforcement may invent tags: keep only allowed ones.
        chosen = [t for t in _strings(data.get("tags"), "tags", 50) if t in allowed]
        result.tags = list(dict.fromkeys(chosen))[: config.tags.max_tags]
    if config.document_date.enabled:
        result.document_date = _iso_date(data.get("document_date"))
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
