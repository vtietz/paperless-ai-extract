"""Match model-proposed names to existing taxonomy objects.

Order: configured alias -> exact normalized name (unowned objects first) ->
fuzzy match with the same difflib rule Paperless's native AI uses.
"""
from __future__ import annotations

import difflib
import re

from .models import Item


def compact(value: str) -> str:
    return re.sub(r"[^\w]", "", value.casefold())


def recipient_match(printed: str, labels: list[str], config) -> str | None:
    """Unique full-name/explicit-alias match; never infer a person from a surname."""
    def key(value):
        people = re.split(r'\s*(?:&|/|\bund\b|\band\b)\s*', value.casefold())
        parts = []
        for person in people:
            words = re.findall(r"\w+", person)
            words = tuple(sorted(w for w in words if w not in {'herr', 'frau', 'mr', 'mrs', 'ms'}))
            if not words:
                return ()
            parts.append(words)
        return tuple(sorted(parts))
    wanted = key(printed)
    if not wanted:
        return None

    def ordered_people(value):
        people = re.split(r'\s*(?:&|/|\bund\b|\band\b)\s*', value.casefold())
        return [tuple(w for w in re.findall(r'\w+', person)
                      if w not in {'herr', 'frau', 'mr', 'mrs', 'ms'})
                for person in people]

    def person_matches(actual, canonical):
        if sorted(actual) == sorted(canonical):
            return True
        # Keep the complete canonical given-name prefix and surname. Only
        # additional full given names between them may be omitted locally.
        if len(canonical) < 2 or len(actual) <= len(canonical):
            return False
        prefix = canonical[:-1]
        extra = actual[len(prefix):-1]
        return (actual[:len(prefix)] == prefix and actual[-1] == canonical[-1]
                and bool(extra) and all(len(w) >= 2 and w.isalpha() for w in extra))

    def expanded_match(label):
        actual, canonical = ordered_people(printed), ordered_people(label)
        if len(actual) != len(canonical):
            return False
        # One-to-one matching preserves each person's first/surname pairing.
        choices = [set(i for i, person in enumerate(canonical) if person_matches(p, person))
                   for p in actual]
        choices.sort(key=len)
        def assign(index, used):
            if index == len(choices):
                return True
            return any(assign(index + 1, used | {i}) for i in choices[index] - used)
        return assign(0, set())

    matches = {label for label in labels
               if label not in (config.unassigned, config.shared)
               and (any(key(variant) == wanted for variant in
                        [label] + config.aliases.get(label, [])) or expanded_match(label))}
    return next(iter(matches)) if len(matches) == 1 else None


def _native(value: str) -> str:
    return re.sub(r"[^\w\s]", "", value.lower()).strip()


def apply_alias(name: str, aliases: dict[str, str]) -> str:
    table = {compact(key): value for key, value in aliases.items()}
    return table.get(compact(name), name.strip())


# Legal forms and filler words carry no identity ("Stadtwerke GmbH" ~ "Stadtwerke").
_FILLER = {"gmbh", "mbh", "ag", "kg", "co", "ug", "se", "ev", "und", "and", "der", "die",
           "das", "the", "of", "für", "fur", "von", "inc", "ltd", "llc"}


def _words(text: str) -> list[str]:
    # Words under 4 characters ("com", "tüv") are too common to count on their own;
    # names made only of such words match as a whole name.
    return [w for w in re.findall(r"\w+", text.casefold()) if len(w) >= 4 and w not in _FILLER]


def _whole_name(name: str):
    """Regex for the name as separate words; punctuation/spacing may differ."""
    parts = re.findall(r"\w+", name.casefold())
    return re.compile(r"(?<!\w)" + r"\W*".join(map(re.escape, parts)) + r"(?!\w)") if parts else None


def shortlist(content: str, items: list[Item], aliases: dict[str, str], limit: int,
              fuzzy_cutoff: float = 0.85) -> list[str]:
    """Existing names that probably occur in the document text, best first.

    Score 1.0 for the whole name or a configured alias in the text, otherwise the
    share of the name's significant words found in it (fuzzy for OCR errors in
    longer words). Names scoring below 0.6 are left out, so names of up to two
    significant words must match completely.
    """
    text = content.casefold()
    words = set(_words(content))
    long_words = [w for w in words if len(w) >= 5]
    names = {item.name for item in items}
    scores: dict[str, float] = {}
    for name in names:
        pattern = _whole_name(name)
        if pattern and pattern.search(text):
            scores[name] = 1.0
            continue
        parts = _words(name)
        if not parts:
            continue
        hits = sum(1 for w in parts if w in words or (
            len(w) >= 5 and difflib.get_close_matches(w, long_words, n=1, cutoff=fuzzy_cutoff)))
        if hits:
            scores[name] = hits / len(parts)
    for alias, target in aliases.items():
        pattern = _whole_name(alias)
        if target in names and pattern and pattern.search(text):
            scores[target] = 1.0
    ranked = sorted((n for n, s in scores.items() if s >= 0.6),
                    key=lambda n: (-scores[n], n.casefold()))
    return ranked[:limit]


def find(name: str, items: list[Item], fuzzy_threshold: float) -> Item | None:
    key = compact(name)
    if not key:
        return None
    exact = [item for item in items if compact(item.name) == key]
    if exact:
        return sorted(exact, key=lambda i: (i.owner is not None, i.id))[0]
    if fuzzy_threshold >= 1:
        return None
    names = [_native(item.name) for item in items]
    match = difflib.get_close_matches(_native(name), names, n=1, cutoff=fuzzy_threshold)
    return items[names.index(match[0])] if match else None
