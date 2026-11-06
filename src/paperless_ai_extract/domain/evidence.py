"""Fail-closed evidence checks for model-chosen values.

A model choice is accepted only when the document *text* supports it. For
configured multi-person aliases a bounded second OCR reading of the address
window may confirm what the main OCR missed. Nothing here is a statistical
confidence score; ambiguity always resolves to "not confirmed".
"""
from __future__ import annotations

import re

from ..config import RecipientConfig

_JOINERS = re.compile(r"\s+(?:&|und|and)\s+")
_POSTAL = re.compile(r"\b(?:D[ -]*)?\d{5}\s*[A-Za-zÄÖÜäöüß]", re.IGNORECASE)
_SALUTATION = re.compile(
    r"^\s*(?:(?:Frau|Herr|Familie|Mr\.?|Mrs\.?|Ms\.?)(?:\s*/\s*(?:Frau|Herr))?)[\s:]+",
    re.IGNORECASE)
_SENDER_LABEL = re.compile(r"\b(?:Absender|Auftraggeber|Sender|From)\b", re.IGNORECASE)


def normalize(value: str) -> str:
    return re.sub(r"[^\w]", "", value.casefold())


def occurs_in(value: str, content: str) -> bool:
    key = normalize(value)
    return bool(key) and key in normalize(content)


def joint_address_alias(chosen: str, evidence: str, content: str,
                        aliases: dict[str, list[str]]) -> bool:
    """A configured joint alias printed as a standalone postal address line."""
    if len(_JOINERS.split(chosen)) < 2:
        return False
    quote = normalize(evidence)
    if not quote or quote not in normalize(content):
        return False
    allowed = {normalize(a) for a in aliases.get(chosen, []) if normalize(a)}
    if not allowed:
        return False
    lines = content[:1600].splitlines()
    for index, line in enumerate(lines):
        name = _SALUTATION.sub("", line)
        # OCR may append an adjacent customer-number column to the name line.
        name = re.sub(r"\s+\d[\d/ .-]*$", "", name)
        key = normalize(name)
        if key not in allowed or key not in quote:
            continue
        preceding = " ".join(t.strip() for t in lines[max(0, index - 3):index] if t.strip())
        if _SENDER_LABEL.search(preceding):
            continue
        following = [t.strip() for t in lines[index + 1:] if t.strip()][:4]
        for postal_index, text in enumerate(following):
            if _POSTAL.search(text) and any(
                    re.search(r"\d+[a-z]?\s*$", street, re.IGNORECASE)
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
    between = r"[\s,.-]+(?:[A-Za-zÄÖÜäöüß.-]{1,30}[\s,.-]+){0,3}"
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
    if joint_address_alias(chosen, evidence, content, config.aliases):
        return chosen
    for person in _JOINERS.split(chosen):
        names = [person] + config.aliases.get(person, [])
        if not any(_named_person_present(name, quote, evidence) for name in names):
            return unassigned
    return chosen


def confirmed_joint_address(readings: list[str], aliases: dict[str, list[str]]) -> str | None:
    """All readings must independently find the same single configured joint alias."""
    if len(readings) < 2:
        return None
    agreed = []
    for content in readings:
        candidates = {
            chosen for chosen, variants in aliases.items()
            if any(joint_address_alias(chosen, v, content, aliases) for v in variants)}
        if len(candidates) != 1:
            return None
        agreed.append(next(iter(candidates)))
    return agreed[0] if len(set(agreed)) == 1 else None


