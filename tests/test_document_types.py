"""Existing document types offered to the model, creation policy and aliases."""
from paperless_ai_extract.domain.models import Extraction, Item
from paperless_ai_extract.domain.planner import plan_document, selectable_document_types
from paperless_ai_extract.domain.prompt import render_instructions
from paperless_ai_extract.domain.schema import build_schema

from conftest import JOINT, FakeLLM, answer, letter_doc

BUILTIN = "${field_instructions}"


def extraction(document_type: str) -> Extraction:
    return Extraction(kind="household", title="Folien", correspondent="Stadtwerke Musterstadt",
                      document_type=document_type, addressee_text="Muster/Beispiel",
                      recipient=JOINT)


def type_changes(config, taxonomy, document_type):
    p = plan_document(config, extraction(document_type), letter_doc(), taxonomy, {},
                      lambda: None, "first_run")
    return [c for c in p.changes if c.field == "document_type"]


def test_existing_types_are_listed_sorted_without_excluded(config, taxonomy):
    config.extraction.document_types.excluded = ["Article"]
    taxonomy.document_types.append(Item(22, "angebot"))
    assert selectable_document_types(config, taxonomy) == ["angebot", "Rechnung"]


def test_listing_can_be_disabled_or_capped(config, taxonomy):
    config.extraction.document_types.offer_existing = False
    assert selectable_document_types(config, taxonomy) == []
    config.extraction.document_types.offer_existing = True
    config.extraction.document_types.max_listed = 1
    assert selectable_document_types(config, taxonomy) == []


def test_builtin_prompt_prefers_existing_types_and_allows_new(config):
    text = render_instructions(config, BUILTIN, ["Unassigned"], None, ["Rechnung", "Vertrag"])
    assert '["Rechnung", "Vertrag"]' in text and "only if none fits, one new" in text


def test_builtin_prompt_restricts_types_when_creation_disabled(config):
    config.taxonomy.create_document_types = False
    text = render_instructions(config, BUILTIN, ["Unassigned"], None, ["Rechnung"])
    assert 'one type from ["Rechnung"], or [] if none fits' in text and "new" not in text


def test_builtin_prompt_without_types_keeps_free_type(config):
    text = render_instructions(config, BUILTIN, ["Unassigned"], None, [])
    assert "one short, general document type" in text


def test_custom_prompt_placeholder(config):
    text = render_instructions(config, "Types: ${document_type_options}", ["Unassigned"],
                               None, ["Präsentation"])
    assert text == 'Types: ["Präsentation"]'


def test_schema_enum_only_when_restricted(config):
    free = build_schema(config.extraction, ["Unassigned"], None, None)
    assert "enum" not in free["properties"]["document_types"]["items"]
    strict = build_schema(config.extraction, ["Unassigned"], None, ["Rechnung"])
    assert strict["properties"]["document_types"]["items"]["enum"] == ["Rechnung"]


def test_alias_maps_model_name_to_existing_type(config, taxonomy):
    config.taxonomy.document_type_aliases = {"Stromrechnung": "Rechnung"}
    [change] = type_changes(config, taxonomy, "Stromrechnung")
    assert change.action == "fill" and change.value == 20


def test_unknown_type_with_creation_disabled_is_only_proposed(config, taxonomy):
    config.taxonomy.create_document_types = False
    [change] = type_changes(config, taxonomy, "Präsentation")
    assert change.action == "propose"


def test_context_offers_types_to_model_and_enforces_enum(build, config):
    config.taxonomy.create_document_types = False
    llm = FakeLLM(answer(document_types=["Rechnung"]))
    extractor, _ = build([letter_doc()], llm, cfg=config)
    ctx = extractor.context()
    assert ctx.schema["properties"]["document_types"]["items"]["enum"] == ["Article", "Rechnung"]
    extractor.analyse(1, ctx)
    prompt, _, schema = llm.calls[0]
    assert schema == ctx.schema


def test_fingerprint_changes_when_a_type_is_added(build, config):
    extractor, store = build([letter_doc()], FakeLLM(answer()), cfg=config)
    config.extraction.prompt_file = None
    extractor.template = None
    before = extractor.context().fingerprint
    store.tax.document_types.append(Item(23, "Präsentation"))
    assert extractor.context().fingerprint != before
