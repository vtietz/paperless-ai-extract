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


def _native(value: str) -> str:
    return re.sub(r"[^\w\s]", "", value.lower()).strip()


def apply_alias(name: str, aliases: dict[str, str]) -> str:
    table = {compact(key): value for key, value in aliases.items()}
    return table.get(compact(name), name.strip())


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
