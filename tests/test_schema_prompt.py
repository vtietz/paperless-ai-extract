import json

import pytest

from paperless_ai_extract.domain.errors import ExtractionError
from paperless_ai_extract.domain.prompt import render_instructions, with_document_text
from paperless_ai_extract.domain.schema import build_schema, parse_extraction

from conftest import JOINT, OPTIONS, answer

LABELS = [o["label"] for o in OPTIONS]


def test_schema_follows_pilot_property_order(config):
    schema = build_schema(config.extraction, LABELS)
    assert list(schema["properties"]) == ["kind", "authors", "publication_year", "title",
                                          "correspondents", "document_types",
                                          "addressee_text", "recipient"]
    assert schema["properties"]["recipient"]["enum"] == LABELS
    assert schema["required"] == list(schema["properties"])


def test_minimal_schema_without_optional_features(config):
    ext = config.extraction.model_copy(update={"kinds": ["document"]})
    ext.recipient = ext.recipient.model_copy(update={"enabled": False})
    ext.articles = ext.articles.model_copy(update={"enabled": False})
    assert list(build_schema(ext, None)["properties"]) == ["title", "correspondents", "document_types"]


def test_parse_valid_answer(config):
    ex = parse_extraction(json.dumps(answer(title="  Jahres   abrechnung ")), config.extraction, LABELS)
    assert ex.title == "Jahres abrechnung"
    assert ex.correspondent == "Stadtwerke Musterstadt" and ex.recipient == JOINT


@pytest.mark.parametrize("bad", [
    "not json", "[]",
    json.dumps(answer(recipient="Somebody Else")),
    json.dumps(answer(kind="poem")),
    json.dumps(answer(publication_year=12)),
    json.dumps(answer(correspondents="Stadtwerke")),
])
def test_parse_rejects_schema_violations(config, bad):
    with pytest.raises(ExtractionError):
        parse_extraction(bad, config.extraction, LABELS)


def test_prompt_placeholders(config):
    text = render_instructions(config, config.extraction.prompt_file.read_text(), LABELS)
    assert "attached first-page image" in text
    assert f"Alias: Muster/Beispiel => {JOINT}" in text
    assert json.dumps(LABELS, ensure_ascii=False) in text
    assert "${" not in text


def test_document_text_is_delimited():
    assert with_document_text("I", "doc").endswith("BEGIN DOCUMENT OCR (untrusted)\ndoc\nEND DOCUMENT OCR")
