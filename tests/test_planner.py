"""Policy rules of the pure planner."""
from paperless_ai_extract.domain.models import Extraction
from paperless_ai_extract.domain.messages import Messages
from paperless_ai_extract.domain.planner import note_text, plan_document

from conftest import AUTHORS_FIELD, JOINT, LETTER, RECIPIENT_FIELD, letter_doc

ALIASES = {"Stadtwerk Musterstadt GmbH": "Stadtwerke Musterstadt"}


def extraction(**kw) -> Extraction:
    data = dict(kind="household", title="Jahresabrechnung Strom 2025",
                correspondent="Stadtwerke Musterstadt", document_type="Rechnung",
                addressee_text="Muster/Beispiel", recipient=JOINT)
    data.update(kw)
    return Extraction(**data)


def plan(config, taxonomy, ex, doc, mode="first_run", confirm=lambda: None):
    return plan_document(config, ex, doc, taxonomy, ALIASES, confirm, mode)


def by_field(p):
    return {(c.field, c.action): c for c in p.changes}


def test_first_run_fills_empty_fields(config, taxonomy):
    p = plan(config, taxonomy, extraction(), letter_doc())
    c = by_field(p)
    assert c[("title", "fill")].value == "Jahresabrechnung Strom 2025"   # filename title = empty
    assert c[("correspondent", "fill")].value == 10
    assert c[("document_type", "fill")].value == 20
    assert c[("recipient", "fill")].value == "opt-joint"
    assert not p.proposals and not p.review


def test_existing_values_are_never_overwritten(config, taxonomy):
    doc = letter_doc(title="Meine Abrechnung", correspondent=11,
                     custom_fields={RECIPIENT_FIELD["id"]: "opt-alex"})
    c = by_field(plan(config, taxonomy, extraction(), doc))
    assert c[("title", "propose")].current_display == "Meine Abrechnung"
    assert c[("correspondent", "propose")].display == "Stadtwerke Musterstadt"
    assert c[("recipient", "propose")].value == "opt-joint"
    assert not any(ch.action == "fill" and ch.field != "document_type" for ch in c.values())


def test_rerun_only_proposes(config, taxonomy):
    p = plan(config, taxonomy, extraction(), letter_doc(), mode="rerun")
    assert {c.field for c in p.proposals} >= {"title", "correspondent", "document_type", "recipient"}
    assert not p.fills


def test_identical_values_produce_no_change(config, taxonomy):
    doc = letter_doc(title="Jahresabrechnung Strom 2025", correspondent=10, document_type=20,
                     custom_fields={RECIPIENT_FIELD["id"]: "opt-joint"})
    assert plan(config, taxonomy, extraction(), doc).changes == []


def test_alias_maps_to_existing_correspondent(config, taxonomy):
    p = plan(config, taxonomy, extraction(correspondent="Stadtwerk Musterstadt GmbH"), letter_doc())
    assert by_field(p)[("correspondent", "fill")].value == 10


def test_new_correspondent_without_text_evidence_is_only_proposed(config, taxonomy):
    p = plan(config, taxonomy, extraction(correspondent="Netzbetreiber Nord"), letter_doc())
    c = by_field(p)[("correspondent", "propose")]
    assert c.create == ("correspondents", "Netzbetreiber Nord") and not c.verified
    assert p.review


def test_new_correspondent_with_text_evidence_is_created(config, taxonomy):
    config.taxonomy.new_correspondents = "create"
    doc = letter_doc(content=LETTER + "\nNetzbetreiber Nord GmbH")
    c = by_field(plan(config, taxonomy, extraction(correspondent="Netzbetreiber Nord"), doc))
    assert c[("correspondent", "fill")].create == ("correspondents", "Netzbetreiber Nord")


def test_unverified_recipient_fills_unassigned_and_proposes(config, taxonomy):
    ex = extraction(recipient="Kim Muster", addressee_text="Kim Muster")
    p = plan(config, taxonomy, ex, letter_doc())
    c = by_field(p)
    assert c[("recipient", "fill")].value == "opt-none"
    proposal = c[("recipient", "propose")]
    assert proposal.value == "opt-kim" and proposal.expect == "opt-none" and not proposal.verified
    assert p.review


def test_address_window_confirmation(config, taxonomy):
    content = "Jahresabrechnung ohne lesbare Adresse"
    calls = []

    def confirm():
        calls.append(1)
        return JOINT
    p = plan(config, taxonomy, extraction(addressee_text="x"), letter_doc(content=content),
             confirm=confirm)
    assert by_field(p)[("recipient", "fill")].value == "opt-joint"
    assert calls and any("address-window" in i for i in p.info)


def test_address_window_not_used_when_recipient_already_set(config, taxonomy):
    doc = letter_doc(content="x", custom_fields={RECIPIENT_FIELD["id"]: "opt-alex"})
    calls = []
    plan(config, taxonomy, extraction(addressee_text="nope"), doc,
         confirm=lambda: calls.append(1))
    assert not calls


def test_article_fields(config, taxonomy):
    text = "i-com 3/2007\nUsability Testing\nAlex Muster, Robin Beispiel\nAbstract"
    ex = extraction(kind="article", title="Usability Testing", correspondent="i-com",
                    document_type="Article", authors=["Alex Muster", "Erfundene Person"],
                    publication_year=2007, recipient="Unassigned", addressee_text="")
    p = plan(config, taxonomy, ex, letter_doc(content=text))
    c = by_field(p)
    assert c[("correspondent", "fill")].value == 12
    assert c[("authors", "fill")].value == "Alex Muster"
    assert c[("created", "fill")].value == "2007-01-01"
    assert ("recipient", "fill") not in c                     # articles have no recipient
    assert any("Erfundene Person" in i for i in p.info) and p.review


def test_article_created_only_on_first_bibliography_pass(config, taxonomy):
    text = "i-com 2007 Alex Muster"
    ex = extraction(kind="article", correspondent="i-com", document_type="Article",
                    authors=["Alex Muster"], publication_year=2007, recipient="Unassigned")
    doc = letter_doc(content=text, custom_fields={AUTHORS_FIELD["id"]: "Alex Muster"})
    c = by_field(plan(config, taxonomy, ex, doc))
    assert ("created", "fill") not in c and ("created", "propose") in c


def test_article_journal_must_be_printed(config, taxonomy):
    ex = extraction(kind="article", correspondent="i-com", recipient="Unassigned")
    c = by_field(plan(config, taxonomy, ex, letter_doc(content="no journal here")))
    assert ("correspondent", "propose") in c


def test_policy_field_selection(config_factory, taxonomy):
    cfg = config_factory("policy: {fields: [title]}\n")
    p = plan(cfg, taxonomy, extraction(), letter_doc())
    assert {c.field for c in p.changes} == {"title"}


def test_note_lists_proposals_and_fills(config, taxonomy):
    doc = letter_doc(title="Meine Abrechnung")
    text = note_text(plan(config, taxonomy, extraction(), doc), "m", Messages("en"), "AI: apply")
    assert 'Title: "Meine Abrechnung" -> "Jahresabrechnung Strom 2025"' in text
    assert "Filled automatically:" in text and '"AI: apply"' in text
