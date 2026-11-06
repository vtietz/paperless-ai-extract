"""Generic features: env-only config, built-in prompt, tags, document date,
locale rules, German notes."""
import json

import pytest

from paperless_ai_extract.config import AddressRulesConfig, ConfigError, RecipientConfig, load_config
from paperless_ai_extract.domain.evidence import date_supported, validated_recipient
from paperless_ai_extract.domain.messages import Messages
from paperless_ai_extract.domain.models import Extraction
from paperless_ai_extract.domain.planner import note_text, plan_document, selectable_tags
from paperless_ai_extract.domain.prompt import render_instructions
from paperless_ai_extract.domain.schema import build_schema, parse_extraction

from conftest import TAGS, FakeLLM, answer, letter_doc

ENV = {"PAPERLESS_URL": "http://paperless:8000", "PAPERLESS_TOKEN": "t",
       "LLM_BASE_URL": "http://ollama:11434", "LLM_MODEL": "qwen3.5:4b"}


# -- configuration ----------------------------------------------------------

def test_env_only_configuration_without_file(tmp_path):
    cfg = load_config(tmp_path / "missing.yaml", environ=ENV)
    assert cfg.paperless.url == "http://paperless:8000" and cfg.llm.model == "qwen3.5:4b"
    assert cfg.extraction.prompt_file is None and cfg.input.mode == "image"
    assert cfg.queue.create_missing_tags is True


def test_generic_env_overrides_win_over_yaml(config_factory, tmp_path):
    config_factory()
    env = {**ENV, "PAE__EXTRACTION__TAGS__ENABLED": "true",
           "PAE__EXTRACTION__TAGS__ALLOWED": "[Steuer, Strom]",
           "PAE__LLM__OPTIONS": "{num_ctx: 8192}", "LLM_MODEL": "other"}
    cfg = load_config(tmp_path / "config.yaml", environ=env)
    assert cfg.extraction.tags.enabled and cfg.extraction.tags.allowed == ["Steuer", "Strom"]
    assert cfg.llm.options == {"num_ctx": 8192} and cfg.llm.model == "other"
    assert cfg.extraction.recipient.enabled          # untouched YAML values remain


def test_missing_file_without_env_is_an_error(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "missing.yaml", environ={})


def test_env_only_requires_llm_settings(tmp_path):
    with pytest.raises(ConfigError, match="llm"):
        load_config(tmp_path / "missing.yaml", environ={"PAPERLESS_URL": "x", "PAPERLESS_TOKEN": "t"})


# -- built-in prompt --------------------------------------------------------

def test_builtin_prompt_lists_only_enabled_fields(tmp_path):
    env = {**ENV, "PAE__EXTRACTION__TAGS__ENABLED": "true",
           "PAE__EXTRACTION__DOCUMENT_DATE__ENABLED": "true",
           "PAE__EXTRACTION__LANGUAGE": "German"}
    cfg = load_config(tmp_path / "none.yaml", environ=env)
    text = render_instructions(cfg, None, None, ["Steuer", "Strom"])
    assert "title: concise title in German" in text
    assert '["Steuer", "Strom"]' in text and "document_date" in text
    assert "- recipient:" not in text and "authors" not in text and "${" not in text


def test_minimal_schema_matches_builtin_prompt(tmp_path):
    cfg = load_config(tmp_path / "none.yaml", environ=ENV)
    assert list(build_schema(cfg.extraction, None)["properties"]) == [
        "title", "correspondents", "document_types"]


# -- tags ---------------------------------------------------------------------


def test_selectable_tags_exclude_inbox_and_queue_tags(config, taxonomy):
    names = [t.name for t in selectable_tags(config, taxonomy)]
    assert names == ["Steuer", "Strom", "Versicherung"]
    config.extraction.tags.allowed = ["Strom", "Inbox", "AI: pending"]
    assert [t.name for t in selectable_tags(config, taxonomy)] == ["Strom"]


def test_tag_schema_is_an_enum_and_unknown_tags_are_dropped(config):
    config.extraction.tags.enabled = True
    schema = build_schema(config.extraction, ["Unassigned"], ["Steuer", "Strom"])
    assert schema["properties"]["tags"]["items"]["enum"] == ["Steuer", "Strom"]
    raw = json.dumps(answer(recipient="Unassigned", tags=["Strom", "Erfunden", "Strom"]))
    ex = parse_extraction(raw, config.extraction, ["Unassigned"] + [], ["Steuer", "Strom"])
    assert ex.tags == ["Strom"]


def _tag_extraction(**kw):
    data = dict(kind="household", title="T", correspondent=None, document_type=None,
                recipient="Unassigned", tags=["Strom", "Steuer"])
    data.update(kw)
    return Extraction(**data)


def test_tags_are_added_on_first_run_and_proposed_on_rerun(config, taxonomy):
    config.extraction.tags.enabled = True
    doc = letter_doc(tags=[TAGS["pending"], 40])          # already has "Steuer"
    first = plan_document(config, _tag_extraction(), doc, taxonomy, {}, lambda: None, "first_run")
    fill = next(c for c in first.fills if c.field == "tags")
    assert fill.value == [42] and fill.display == "+ Strom"
    rerun = plan_document(config, _tag_extraction(), doc, taxonomy, {}, lambda: None, "rerun")
    assert [c.field for c in rerun.proposals if c.field == "tags"] == ["tags"]


def test_tags_written_additively_and_applied(build, config):
    config.extraction.tags.enabled = True
    extractor, store = build([letter_doc(tags=[TAGS["pending"], 41])],
                             FakeLLM(answer(tags=["Strom"])), cfg=config)
    extractor.process(1, extractor.context())
    assert 41 in store.docs[1].tags and 42 in store.docs[1].tags


# -- document date --------------------------------------------------------------

@pytest.mark.parametrize("text", ["Datum: 12.03.2025", "2025-03-12", "12. März 2025",
                                  "March 12, 2025", "12/03/25"])
def test_date_supported_formats(text):
    assert date_supported("2025-03-12", text)


def test_date_not_supported():
    assert not date_supported("2025-03-12", "Rechnung vom 13.03.2025")
    assert not date_supported("not-a-date", "x")


def _date_config(config, first_run="propose"):
    config.extraction.document_date.enabled = True
    config.extraction.document_date.first_run = first_run
    return config


def test_document_date_is_proposed_by_default(config, taxonomy):
    _date_config(config)
    doc = letter_doc(content="Rechnung vom 12.03.2025", created="2025-04-01")
    ex = _tag_extraction(tags=[], document_date="2025-03-12")
    plan = plan_document(config, ex, doc, taxonomy, {}, lambda: None, "first_run")
    change = next(c for c in plan.changes if c.field == "created")
    assert change.action == "propose" and change.verified


def test_document_date_fill_mode_requires_evidence(config, taxonomy):
    _date_config(config, "fill")
    ex = _tag_extraction(tags=[], document_date="2025-03-12")
    ok = plan_document(config, ex, letter_doc(content="vom 12.03.2025", created="2025-04-01"),
                       taxonomy, {}, lambda: None, "first_run")
    assert any(c.field == "created" and c.action == "fill" for c in ok.changes)
    bad = plan_document(config, ex, letter_doc(content="kein Datum", created="2025-04-01"),
                        taxonomy, {}, lambda: None, "first_run")
    created = [c for c in bad.changes if c.field == "created"]
    assert [c.action for c in created] == ["propose"] and not created[0].verified


def test_same_date_produces_no_change(config, taxonomy):
    _date_config(config, "fill")
    ex = _tag_extraction(tags=[], document_date="2025-04-01")
    plan = plan_document(config, ex, letter_doc(created="2025-04-01"), taxonomy, {},
                         lambda: None, "first_run")
    assert not [c for c in plan.changes if c.field == "created"]


# -- locale rules and notes ----------------------------------------------------

def test_address_rules_are_configurable_for_other_locales():
    uk = RecipientConfig(enabled=True, aliases={"Alex & Sam Smith": ["A & S Smith"]},
                         address_rules=AddressRulesConfig(
                             postal_code=r"\b[A-Z]{1,2}\d[A-Z\d]? ?\d[A-Z]{2}\b",
                             street_number=r"^\d+\s+\w+", sender_labels=["Return address"],
                             salutations=["Mr", "Mrs"], name_joiners=["&", "and"]))
    text = "A & S Smith\n12 High Street\nLondon SW1A 1AA"
    assert validated_recipient("Alex & Sam Smith", "A & S Smith", text, uk) == "Alex & Sam Smith"
    german_rules = RecipientConfig(enabled=True, aliases=uk.aliases)
    assert validated_recipient("Alex & Sam Smith", "A & S Smith", text, german_rules) == "Unassigned"


def test_german_notes(config, taxonomy):
    config.policy.notes_language = "de"
    doc = letter_doc(title="Eigener Titel")
    ex = _tag_extraction(title="Neuer Titel", tags=[])
    text = note_text(plan_document(config, ex, doc, taxonomy, {}, lambda: None, "first_run"),
                     "m", Messages("de"), "AI: apply")
    assert "KI-Extraktion (m, Erstanalyse)" in text and 'Titel: "Eigener Titel" -> "Neuer Titel"' in text


def test_env_values_with_colons_stay_strings(tmp_path):
    env = {**ENV, "PAE__QUEUE__TAGS__PENDING": "AI: pending",
           "PAE__EXTRACTION__TAGS__ALLOWED": "[Tax, Insurance]",
           "PAE__QUEUE__POLL_INTERVAL": "10"}
    cfg = load_config(tmp_path / "none.yaml", environ=env)
    assert cfg.queue.tags.pending == "AI: pending"
    assert cfg.extraction.tags.allowed == ["Tax", "Insurance"] and cfg.queue.poll_interval == 10
    with pytest.raises(ConfigError, match="PAE__LLM__OPTIONS"):
        load_config(tmp_path / "none.yaml", environ={**ENV, "PAE__LLM__OPTIONS": "{broken: ["})


def test_env_example_file_is_valid(tmp_path):
    from pathlib import Path
    example = Path(__file__).parent.parent / "examples" / "ai-extract.env.example"
    env = {}
    for line in example.read_text().splitlines():
        line = line.lstrip("# ").strip() if line.startswith("# PAE__") or line.startswith("# INPUT_") else line
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            env[key] = value
    cfg = load_config(tmp_path / "none.yaml", environ=env)
    assert cfg.queue.tags.pending == "AI: pending" and cfg.extraction.tags.enabled
