"""Correspondent shortlist from the OCR text and the new-item policy."""
from paperless_ai_extract.config import TaxonomyConfig
from paperless_ai_extract.domain.matching import shortlist
from paperless_ai_extract.domain.models import Item
from paperless_ai_extract.domain.planner import offered_correspondents, plan_document
from paperless_ai_extract.domain.prompt import render_instructions

from conftest import LETTER, FakeLLM, answer, letter_doc

ITEMS = [Item(1, "Stadtwerke Musterstadt"), Item(2, "TÜV SÜD Industrie Service GmbH"),
         Item(3, "Versicherung Beispiel AG"), Item(4, "Landeshauptstadt Dresden"),
         Item(5, "i-com")]


def test_whole_name_in_text_ranks_first():
    text = "Stadtwerke Musterstadt, Postfach 1\nRechnung"
    assert shortlist(text, ITEMS, {}, 5)[0] == "Stadtwerke Musterstadt"


def test_partial_and_ocr_damaged_names_are_found():
    text = "TÜV SÜD Industrie Servlce GmbH · Dreschergasse"   # OCR: Servlce
    assert "TÜV SÜD Industrie Service GmbH" in shortlist(text, ITEMS, {}, 5)


def test_unrelated_names_are_left_out_and_limit_applies():
    text = "Stadtwerke Musterstadt and Versicherung Beispiel AG"
    names = shortlist(text, ITEMS, {}, 1)
    assert names == ["Stadtwerke Musterstadt"]
    assert "Landeshauptstadt Dresden" not in shortlist(text, ITEMS, {}, 5)


def test_alias_in_text_lists_its_target():
    text = "Ihre Telekom informiert"
    items = ITEMS + [Item(6, "Telekom Deutschland GmbH")]
    assert shortlist(text, items, {"Ihre Telekom": "Telekom Deutschland GmbH"}, 5)[0] \
        == "Telekom Deutschland GmbH"


def test_short_names_need_the_whole_name():
    assert "i-com" not in shortlist("Mail: info@example.com", ITEMS, {}, 5)
    assert "i-com" in shortlist("i-com 3/2007, Oldenbourg", ITEMS, {}, 5)


def test_legal_forms_alone_do_not_match():
    assert shortlist("Muster GmbH & Co. KG", ITEMS, {}, 5) == []


def test_offer_modes(config, taxonomy):
    content = LETTER
    assert offered_correspondents(config, taxonomy, content, {}) == ["Stadtwerke Musterstadt"]
    config.extraction.correspondents.offer = "all"
    assert len(offered_correspondents(config, taxonomy, content, {})) == 3
    config.extraction.correspondents.max_listed = 2           # too many: shortlist instead
    assert offered_correspondents(config, taxonomy, content, {}) == ["Stadtwerke Musterstadt"]
    config.extraction.correspondents.offer = "none"
    assert offered_correspondents(config, taxonomy, content, {}) == []


def test_prompt_lists_offered_correspondents(config):
    text = render_instructions(config, "${field_instructions}", ["Unassigned"], None, [],
                               ["Stadtwerke Musterstadt"])
    assert 'if it is one of ["Stadtwerke Musterstadt"], use that exact name' in text
    custom = render_instructions(config, "C=${correspondent_options}", ["Unassigned"], None,
                                 [], ["A", "B"])
    assert custom == 'C=["A", "B"]'


def test_shortlist_is_part_of_the_cache_key_and_the_prompt(build):
    llm = FakeLLM(answer())
    extractor, store = build([letter_doc()], llm)
    ctx = extractor.context()
    outcome = extractor.analyse(1, ctx)
    assert outcome.metrics["offered_correspondents"] == ["Stadtwerke Musterstadt"]
    store.tax.correspondents.append(Item(13, "Hauptstrasse Musterstadt"))  # both words in text
    extractor.analyse(1, extractor.context())
    assert len(llm.calls) == 2                       # list changed: not served from cache


def _correspondent_changes(config, taxonomy, name, content):
    ex = answer(correspondents=[name])
    from paperless_ai_extract.domain.models import Extraction
    extraction = Extraction(kind="household", title=ex["title"], correspondent=name,
                            document_type="Rechnung", addressee_text=ex["addressee_text"],
                            recipient=ex["recipient"])
    p = plan_document(config, extraction, letter_doc(content=content), taxonomy, {},
                      lambda: None, "first_run")
    return [c for c in p.changes if c.field == "correspondent"], p


def test_new_correspondent_is_proposed_by_default(config, taxonomy):
    [change], plan = _correspondent_changes(config, taxonomy, "Netzbetreiber Nord",
                                            LETTER + "\nNetzbetreiber Nord")
    assert change.action == "propose" and change.create == ("correspondents", "Netzbetreiber Nord")
    assert plan.review


def test_new_correspondent_dropped_when_never(config, taxonomy):
    config.taxonomy.new_correspondents = "never"
    changes, plan = _correspondent_changes(config, taxonomy, "Netzbetreiber Nord",
                                           LETTER + "\nNetzbetreiber Nord")
    assert changes == [] and any("Netzbetreiber Nord" in i for i in plan.info)


def test_accepting_a_proposed_new_correspondent_creates_it(build):
    doc = letter_doc(content=LETTER + "\nNetzbetreiber Nord")
    extractor, store = build([doc], FakeLLM(answer(correspondents=["Netzbetreiber Nord"])))
    ctx = extractor.context()
    extractor.process(1, ctx)
    assert ("create", "correspondents", "Netzbetreiber Nord") not in store.writes
    extractor.apply_proposal(1, extractor.context())
    assert ("create", "correspondents", "Netzbetreiber Nord") in store.writes
    assert store.docs[1].correspondent == store.next_id


def test_legacy_create_flags_still_work():
    assert TaxonomyConfig(create_correspondents=True).new_correspondents == "create"
    assert TaxonomyConfig(create_correspondents=False).new_correspondents == "propose"
    assert TaxonomyConfig(create_document_types=False).new_document_types == "never"
    assert TaxonomyConfig(create_document_types=True,
                          new_document_types="propose").new_document_types == "propose"
    assert TaxonomyConfig().new_correspondents == "propose"
