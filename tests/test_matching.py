from paperless_ai_extract.domain.matching import apply_alias, find
from paperless_ai_extract.domain.models import Item

ITEMS = [Item(1, "Stadtwerke Musterstadt", owner=7), Item(2, "Stadtwerke Musterstadt"),
         Item(3, "Versicherung Beispiel AG")]


def test_exact_normalized_match_prefers_unowned():
    assert find("stadtwerke-musterstadt", ITEMS, 0.8).id == 2


def test_fuzzy_match_uses_native_threshold():
    assert find("Versicherung Beispiel", ITEMS, 0.8).id == 3
    assert find("Versicherung Beispiel", ITEMS, 1.0) is None


def test_no_match():
    assert find("Ganz Anders GmbH", ITEMS, 0.8) is None
    assert find("  ", ITEMS, 0.8) is None


def test_alias_is_normalized():
    aliases = {"E-Plus Serwice GmbH": "E-Plus Service GmbH"}
    assert apply_alias("e plus serwice gmbh", aliases) == "E-Plus Service GmbH"
    assert apply_alias(" Other ", aliases) == "Other"
