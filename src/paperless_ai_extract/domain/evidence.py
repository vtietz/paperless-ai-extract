"""Fail-closed evidence checks for model-chosen values.

A model choice is accepted only when the document *text* supports it. For
configured multi-person aliases a bounded second OCR reading of the address
window may confirm what the main OCR missed. Nothing here is a statistical
confidence score; ambiguity always resolves to "not confirmed".

Locale-specific patterns (postal code, salutations, sender labels, name
joiners) come from `AddressRulesConfig`; the defaults cover German and English.
"""
from __future__ import annotations

import re
from functools import lru_cache

from ..config import AddressRulesConfig, RecipientConfig

DEFAULT_RULES = AddressRulesConfig()


def normalize(value: str) -> str:
    return re.sub(r"[^\w]", "", value.casefold())


def occurs_in(value: str, content: str) -> bool:
    key = normalize(value)
    return bool(key) and key in normalize(content)


class _Rules:
    def __init__(self, rules: AddressRulesConfig):
        words = lambda items: "|".join(re.escape(w.rstrip(".")) for w in items if w.strip())
        joiners = "|".join(re.escape(j) for j in rules.name_joiners if j.strip()) or "&"
        self.joiners = re.compile(rf"\s+(?:{joiners})\s+", re.IGNORECASE)
        self.postal = re.compile(rules.postal_code, re.IGNORECASE)
        self.street = re.compile(rules.street_number, re.IGNORECASE)
        salutation = words(rules.salutations)
        self.salutation = re.compile(
            rf"^\s*(?:(?:{salutation})\.?(?:\s*/\s*(?:{salutation})\.?)?)[\s:]+", re.IGNORECASE
        ) if salutation else None
        labels = words(rules.sender_labels)
        self.sender = re.compile(rf"\b(?:{labels})\b", re.IGNORECASE) if labels else None


@lru_cache(maxsize=8)
def _compiled(rules_json: str) -> _Rules:
    return _Rules(AddressRulesConfig.model_validate_json(rules_json))


def _rules(rules: AddressRulesConfig | None) -> _Rules:
    return _compiled((rules or DEFAULT_RULES).model_dump_json())


def split_names(chosen: str, rules: AddressRulesConfig | None = None) -> list[str]:
    return _rules(rules).joiners.split(chosen)


def joint_address_alias(chosen: str, evidence: str, content: str,
                        aliases: dict[str, list[str]],
                        rules: AddressRulesConfig | None = None) -> bool:
    """A configured joint alias printed as a standalone postal address line."""
    r = _rules(rules)
    if len(r.joiners.split(chosen)) < 2:
        return False
    quote = normalize(evidence)
    if not quote or quote not in normalize(content):
        return False
    allowed = {normalize(a) for a in aliases.get(chosen, []) if normalize(a)}
    if not allowed:
        return False
    lines = content[:1600].splitlines()
    for index, line in enumerate(lines):
        name = r.salutation.sub("", line) if r.salutation else line
        # OCR may append an adjacent customer-number column to the name line.
        name = re.sub(r"\s+\d[\d/ .-]*$", "", name)
        key = normalize(name)
        if key not in allowed or key not in quote:
            continue
        preceding = " ".join(t.strip() for t in lines[max(0, index - 3):index] if t.strip())
        if r.sender and r.sender.search(preceding):
            continue
        following = [t.strip() for t in lines[index + 1:] if t.strip()][:4]
        for postal_index, text in enumerate(following):
            if r.postal.search(text) and any(r.street.search(street)
                                             for street in following[:postal_index]):
                return True
    return False


def _named_person_present(name: str, quote: str, evidence: str) -> bool:
    if normalize(name) in quote:
        return True
    parts = name.split()
    if len(parts) != 2:
        return False

    def letters(word: str) -> str:
        return r"\s*".join(re.escape(c) for c in word)
    # up to three middle names / titles between first and last name
    between = r"[\s,.-]+(?:[^\W\d_][\w.-]{0,29}[\s,.-]+){0,3}"
    pattern = r"\b" + letters(parts[0]) + r"\b" + between + letters(parts[1]) + r"\b"
    return bool(re.search(pattern, evidence, re.IGNORECASE))


def validated_recipient(chosen: str, evidence: str, content: str,
                        config: RecipientConfig) -> str:
    """Return `chosen` when the quoted addressee supports it, else unassigned."""
    unassigned = config.unassigned
    if chosen == unassigned:
        return chosen
    quote = normalize(evidence)
    # The quote must come from the document, not from the prompt's label list.
    if not quote or quote not in normalize(content):
        return unassigned
    if config.shared and chosen == config.shared:
        keywords = [k.casefold() for k in config.shared_keywords]
        return chosen if any(k in evidence.casefold() for k in keywords) else unassigned
    if joint_address_alias(chosen, evidence, content, config.aliases, config.address_rules):
        return chosen
    for person in split_names(chosen, config.address_rules):
        names = [person] + config.aliases.get(person, [])
        if not any(_named_person_present(name, quote, evidence) for name in names):
            return unassigned
    return chosen


def confirmed_joint_address(readings: list[str], aliases: dict[str, list[str]],
                            rules: AddressRulesConfig | None = None) -> str | None:
    """All readings must independently find the same single configured joint alias."""
    if len(readings) < 2:
        return None
    agreed = []
    for content in readings:
        candidates = {
            chosen for chosen, variants in aliases.items()
            if any(joint_address_alias(chosen, v, content, aliases, rules) for v in variants)}
        if len(candidates) != 1:
            return None
        agreed.append(next(iter(candidates)))
    return agreed[0] if len(set(agreed)) == 1 else None


def date_supported(iso_date: str, content: str) -> bool:
    """True when the date is printed in a common numeric or ISO form."""
    try:
        year, month, day = (int(p) for p in iso_date.split("-"))
    except ValueError:
        return False
    text = content.casefold()
    d, m, y = day, month, year
    patterns = [
        rf"\b{y}-0?{m}-0?{d}\b",
        rf"\b0?{d}[./-]\s?0?{m}[./-]\s?(?:{y}|{y % 100:02d})\b",
        rf"\b0?{m}/0?{d}/(?:{y}|{y % 100:02d})\b",
    ]
    if any(re.search(p, text) for p in patterns):
        return True
    # "12. März 2025", "March 12, 2025", "12 Mar 2025": day and year near each other
    return bool(re.search(rf"\b0?{d}\.?\s+[^\W\d_]{{3,10}}\.?\s+{y}\b", text)
                or re.search(rf"\b[^\W\d_]{{3,10}}\.?\s+0?{d},?\s+{y}\b", text))
