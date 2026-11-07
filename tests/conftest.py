"""Shared fixtures: a fictional household config and in-memory port fakes."""
from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from paperless_ai_extract.adapters.sqlite_state import SqliteStateStore
from paperless_ai_extract.application.use_cases import MetadataExtractor
from paperless_ai_extract.config import load_config
from paperless_ai_extract.domain.models import DocumentSnapshot, Item, Taxonomy
from paperless_ai_extract.ports import LLMResult

JOINT = "Alex Muster & Sam Beispiel"
OPTIONS = [
    {"id": "opt-alex", "label": "Alex Muster"},
    {"id": "opt-sam", "label": "Sam Beispiel"},
    {"id": "opt-kim", "label": "Kim Muster"},
    {"id": "opt-joint", "label": JOINT},
    {"id": "opt-shared", "label": "Shared"},
    {"id": "opt-none", "label": "Unassigned"},
]
RECIPIENT_FIELD = {"id": 1, "name": "Recipient", "data_type": "select",
                   "extra_data": {"select_options": OPTIONS}}
AUTHORS_FIELD = {"id": 2, "name": "Authors", "data_type": "longtext", "extra_data": {}}

TAGS = {"pending": 101, "apply": 102, "proposal": 103, "review": 104, "error": 105}

CONFIG_YAML = """
paperless:
  url: http://paperless.test
  token: ${TEST_TOKEN:-secret-token}
llm:
  provider: ollama
  base_url: http://ollama.test:11434
  model: vision-model
  options: {temperature: 0.1}
input:
  mode: image
extraction:
  prompt_file: prompt.txt
  kinds: [household, article]
  recipient:
    enabled: true
    shared: Shared
    shared_keywords: [familie]
    aliases:
      "Alex Muster & Sam Beispiel": ["Muster/Beispiel"]
    address_window: {enabled: true}
  articles:
    enabled: true
taxonomy:
  correspondent_aliases: {"Stadtwerk Musterstadt GmbH": "Stadtwerke Musterstadt"}
state:
  path: state.sqlite3
  heartbeat_file: heartbeat
"""

PROMPT = "Classify from ${source_description}.\n${recipient_aliases}\nAllowed: ${recipient_options}\n${input_hint}\n"

LETTER = textwrap.dedent("""\
    Stadtwerke Musterstadt, Postfach 1, 12345 Musterstadt
    Muster/Beispiel
    Hauptstrasse 12
    12345 Musterstadt
    Jahresabrechnung Strom 2025
    Sehr geehrte Familie Muster,
    """)


@pytest.fixture
def config_factory(tmp_path: Path):
    def make(extra: str = "", prompt: str = PROMPT):
        (tmp_path / "prompt.txt").write_text(prompt)
        path = tmp_path / "config.yaml"
        path.write_text(CONFIG_YAML + extra)
        return load_config(path)
    return make


@pytest.fixture
def config(config_factory):
    return config_factory()


def make_taxonomy() -> Taxonomy:
    return Taxonomy(
        correspondents=[Item(10, "Stadtwerke Musterstadt"), Item(11, "Versicherung Beispiel AG"),
                        Item(12, "i-com")],
        document_types=[Item(20, "Rechnung"), Item(21, "Article")],
        tags=[Item(i, name) for name, i in
              {"AI: pending": 101, "AI: apply": 102, "AI: proposal": 103,
               "AI: review": 104, "AI: error": 105}.items()]
             + [Item(1, "Inbox", inbox=True), Item(40, "Steuer"), Item(41, "Versicherung"),
                Item(42, "Strom")],
        custom_fields=[RECIPIENT_FIELD, AUTHORS_FIELD],
    )


@pytest.fixture
def taxonomy() -> Taxonomy:
    return make_taxonomy()


class FakeStore:
    """In-memory DocumentStore recording every write."""

    def __init__(self, taxonomy: Taxonomy, docs: dict[int, DocumentSnapshot]):
        self.tax = taxonomy
        self.docs = docs
        self.notes: dict[int, list[str]] = {}
        self.writes: list[tuple] = []
        self.next_id = 500

    def ping(self):
        return None

    def taxonomy(self) -> Taxonomy:
        return Taxonomy(list(self.tax.correspondents), list(self.tax.document_types),
                        list(self.tax.tags),
                        list(self.tax.custom_fields))

    def document_ids_with_tag(self, tag_id):
        return [d.id for d in self.docs.values() if tag_id in d.tags]

    def document(self, doc_id):
        d = self.docs[doc_id]
        return DocumentSnapshot(**{**d.__dict__, "tags": list(d.tags),
                                   "custom_fields": dict(d.custom_fields)})

    def checksum(self, doc_id, original):
        return f"sum-{doc_id}"

    def download(self, doc_id, original):
        return b"%PDF-1.7 fake", "application/pdf"

    def create_object(self, endpoint, name):
        self.next_id += 1
        item = Item(self.next_id, name)
        getattr(self.tax, endpoint).append(item)
        self.writes.append(("create", endpoint, name))
        return item

    def update_document(self, doc_id, fields):
        if fields:
            self.writes.append(("update", doc_id, dict(fields)))
            for key, value in fields.items():
                setattr(self.docs[doc_id], key, value)

    def set_custom_fields(self, doc_id, values):
        if values:
            self.writes.append(("custom", doc_id, dict(values)))
            self.docs[doc_id].custom_fields.update(values)

    def modify_tags(self, doc_id, add, remove):
        tags = [t for t in self.docs[doc_id].tags if t not in remove]
        self.docs[doc_id].tags = tags + [t for t in add if t not in tags]

    def add_note(self, doc_id, text):
        self.notes.setdefault(doc_id, []).append(text)


class FakeLLM:
    def __init__(self, *answers: dict | str | Exception):
        self.answers = list(answers)
        self.calls: list[tuple] = []

    def generate_json(self, prompt, images, schema):
        self.calls.append((prompt, images, schema))
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        return LLMResult(answer if isinstance(answer, str) else json.dumps(answer), {"eval_count": 1})

    def check(self):
        return "fake"

    def describe(self):
        return {"provider": "fake"}


class FakeRenderer:
    def render(self, data, mime, pages, max_edge):
        return [b"PNG-page"]


class FakeAddressReader:
    def __init__(self, readings=None):
        self.readings = readings
        self.calls = 0

    def read(self, pdf):
        self.calls += 1
        return self.readings


def answer(**overrides) -> dict:
    base = {"kind": "household", "authors": [], "publication_year": None,
            "title": "Jahresabrechnung Strom 2025", "correspondents": ["Stadtwerke Musterstadt"],
            "document_types": ["Rechnung"], "addressee_text": "Muster/Beispiel",
            "recipient": JOINT}
    base.update(overrides)
    return base


def letter_doc(doc_id: int = 1, **fields) -> DocumentSnapshot:
    data = dict(id=doc_id, title="scan_0001", original_file_name="scan_0001.pdf",
                created="2026-11-01", tags=[TAGS["pending"]], content=LETTER)
    data.update(fields)
    return DocumentSnapshot(**data)


@pytest.fixture
def build(config, taxonomy):
    """Build an extractor around fakes: build(docs, llm, address_reader=None)."""
    def make(docs, llm, address_reader=None, cfg=None):
        cfg = cfg or config
        store = FakeStore(taxonomy, {d.id: d for d in docs})
        extractor = MetadataExtractor(cfg, store, llm, FakeRenderer(),
                                      address_reader or FakeAddressReader(),
                                      SqliteStateStore(cfg.state.path))
        return extractor, store
    return make
