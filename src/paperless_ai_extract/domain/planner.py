"""Turn an extraction into a reviewable plan: what to fill, what to propose.

Rules (one engine for import and manual reruns):
  * A value is a *candidate* when it resolves to a usable Paperless value.
  * A candidate is *verified* unless an evidence rule failed.
  * Empty field + fill policy + verified          -> fill.
  * Empty field + fill policy + unverified        -> fill the safe fallback
                                                     (if any) and propose the value.
  * Non-empty field, or propose policy             -> propose (never overwrite).
  * Storage path is only ever filled when empty, never proposed.
"""
from __future__ import annotations

from pathlib import PurePath
from typing import Callable

from ..config import Config
from .evidence import occurs_in, validated_recipient
from .matching import apply_alias, find
from .models import Candidate, Change, DocumentSnapshot, Extraction, Plan, Taxonomy

LABELS = {"title": "Title", "correspondent": "Correspondent",
          "document_type": "Document type", "storage_path": "Storage path",
          "created": "Created", "recipient": "Recipient", "authors": "Authors"}
DIRECT_FIELDS = {"title", "correspondent", "document_type", "storage_path", "created"}
NEVER_PROPOSE = {"storage_path"}


class FieldAccess:
    """Read current values of the logical fields from a snapshot."""

    def __init__(self, config: Config, taxonomy: Taxonomy):
        self.config = config
        self.taxonomy = taxonomy
        recipient = config.extraction.recipient
        self.recipient_field = taxonomy.custom_field(recipient.custom_field) if recipient.enabled else None
        authors = config.extraction.articles.authors_field
        self.authors_field = (taxonomy.custom_field(authors)
                              if config.extraction.articles.enabled and authors else None)

    def recipient_options(self) -> dict[str, str]:
        """label -> option id"""
        if not self.recipient_field:
            return {}
        options = (self.recipient_field.get("extra_data") or {}).get("select_options") or []
        return {o["label"]: o["id"] for o in options}

    def custom_field_id(self, name: str) -> int | None:
        f = self.recipient_field if name == "recipient" else self.authors_field if name == "authors" else None
        return f["id"] if f else None

    def current(self, doc: DocumentSnapshot, name: str):
        if name in DIRECT_FIELDS:
            return getattr(doc, name)
        field_id = self.custom_field_id(name)
        return doc.custom_fields.get(field_id) if field_id is not None else None

    def display(self, name: str, value) -> str:
        if value in (None, ""):
            return "(empty)"
        if name in ("correspondent", "document_type", "storage_path"):
            return self.taxonomy.name_of(name + "s", value) or "(empty)"
        if name == "recipient":
            for label, option_id in self.recipient_options().items():
                if option_id == value:
                    return label
        return str(value)

    def is_empty(self, doc: DocumentSnapshot, name: str, mode: str) -> bool:
        if name == "title":
            stem = PurePath(doc.original_file_name or "").stem
            return not doc.title.strip() or (
                self.config.policy.title_empty_if_filename and bool(stem) and doc.title == stem)
        if name == "created":
            # Paperless always sets a date at import. Only the first bibliography
            # pass may initialise it from a publication year.
            return mode == "first_run" and (
                self.authors_field is None or self.authors_field["id"] not in doc.custom_fields)
        return self.current(doc, name) in (None, "")


def build_candidates(config: Config, ex: Extraction, doc: DocumentSnapshot,
                     taxonomy: Taxonomy, access: FieldAccess,
                     correspondent_aliases: dict[str, str],
                     confirm_address: Callable[[], str | None],
                     mode: str) -> tuple[list[Candidate], list[str], bool]:
    tax_cfg = config.taxonomy
    articles = config.extraction.articles
    is_article = articles.enabled and ex.kind == articles.kind
    article_evidence = is_article and articles.require_text_evidence
    content = doc.content
    candidates: list[Candidate] = []
    info: list[str] = []
    review = False

    if ex.title:
        candidates.append(Candidate("title", ex.title, ex.title))

    if ex.correspondent:
        name = apply_alias(ex.correspondent, correspondent_aliases)
        match = find(name, taxonomy.correspondents, tax_cfg.fuzzy_threshold)
        if match:
            cand = Candidate("correspondent", match.id, match.name)
        elif tax_cfg.create_correspondents:
            cand = Candidate("correspondent", None, f"{name} (new)", create=("correspondents", name))
            if tax_cfg.new_correspondent_requires_text_evidence and not (
                    occurs_in(name, content) or occurs_in(ex.correspondent, content)):
                cand.verified, cand.reason = False, "new name not found in document text"
        else:
            cand = Candidate("correspondent", None, f"{name} (new)", create=("correspondents", name),
                             verified=False, reason="no existing match; creation disabled")
        if article_evidence and cand.verified and not (
                occurs_in(ex.correspondent, content) or occurs_in(name, content)):
            cand.verified, cand.reason = False, "publication not found in document text"
        candidates.append(cand)

    if ex.document_type:
        match = find(ex.document_type, taxonomy.document_types, tax_cfg.fuzzy_threshold)
        if match:
            candidates.append(Candidate("document_type", match.id, match.name))
        else:
            candidates.append(Candidate(
                "document_type", None, f"{ex.document_type} (new)",
                create=("document_types", ex.document_type),
                verified=tax_cfg.create_document_types,
                reason="" if tax_cfg.create_document_types else "no existing match; creation disabled"))

    path_name = tax_cfg.storage_paths.get(ex.kind)
    if path_name:
        path = find(path_name, taxonomy.storage_paths, 1.0)
        if path:
            candidates.append(Candidate("storage_path", path.id, path.name))
        else:
            info.append(f"Configured storage path {path_name!r} does not exist.")

    rc = config.extraction.recipient
    if rc.enabled and not is_article and access.recipient_field and ex.recipient:
        options = access.recipient_options()
        unassigned_id = options.get(rc.unassigned)
        chosen = validated_recipient(ex.recipient, ex.addressee_text, content, rc)
        current = access.current(doc, "recipient")
        if chosen == rc.unassigned and current in (None, "", unassigned_id):
            confirmed = confirm_address()
            if confirmed and confirmed in options:
                chosen = confirmed
                info.append(f"Recipient {confirmed!r} confirmed by address-window OCR.")
        if chosen != rc.unassigned or ex.recipient == rc.unassigned:
            candidates.append(Candidate("recipient", options[chosen], chosen))
            if chosen == rc.unassigned:
                info.append("Recipient could not be determined.")
                review = True
        else:
            quote = " ".join(ex.addressee_text.split())[:120]
            candidates.append(Candidate(
                "recipient", options[ex.recipient], ex.recipient, verified=False,
                reason=f'addressee evidence not confirmed (quote: "{quote}")',
                fallback=unassigned_id, fallback_display=rc.unassigned))
            review = True

    if is_article and access.authors_field and ex.authors:
        if articles.require_text_evidence:
            found = [n for n in ex.authors if occurs_in(n, content)]
            missing = [n for n in ex.authors if n not in found]
        else:
            found, missing = list(ex.authors), []
        if found:
            candidates.append(Candidate("authors", "; ".join(found), "; ".join(found)))
            if missing:
                info.append("Authors not found in document text: " + "; ".join(missing))
                review = True
        else:
            joined = "; ".join(ex.authors)
            candidates.append(Candidate("authors", joined, joined, verified=False,
                                        reason="authors not found in document text"))

    if is_article and articles.created_from_year and ex.publication_year:
        year = ex.publication_year
        current_year = int(doc.created[:4]) if doc.created and doc.created[:4].isdigit() else None
        if current_year != year:
            value = f"{year}-01-01"
            verified = not articles.require_text_evidence or str(year) in content
            candidates.append(Candidate("created", value, value, verified=verified,
                                        reason="" if verified else "year not found in document text"))

    return candidates, info, review


def decide(config: Config, candidates: list[Candidate], doc: DocumentSnapshot,
           access: FieldAccess, mode: str) -> list[Change]:
    allowed = set(config.policy.fields)
    policy = config.policy.first_run if mode == "first_run" else config.policy.rerun
    unassigned = access.recipient_options().get(config.extraction.recipient.unassigned)
    changes: list[Change] = []

    for cand in candidates:
        if cand.field not in allowed:
            continue
        current = access.current(doc, cand.field)
        if cand.value is not None and cand.value == current:
            continue
        current_display = access.display(cand.field, current)

        def change(action, value, display, verified=True, reason="", create=None, expect=current):
            return Change(cand.field, action, current, current_display, value, display,
                          create, verified, reason, expect)

        empty = access.is_empty(doc, cand.field, mode)
        if empty and policy == "fill_empty":
            if cand.verified:
                changes.append(change("fill", cand.value, cand.display, create=cand.create))
                continue
            if cand.fallback is not None and cand.fallback != current:
                changes.append(change("fill", cand.fallback, cand.fallback_display))
                changes.append(change("propose", cand.value, cand.display, False, cand.reason,
                                      cand.create, expect=cand.fallback))
                continue
        if cand.field in NEVER_PROPOSE:
            continue
        if cand.field == "recipient" and cand.value == unassigned:
            continue  # proposing "Unassigned" is noise
        changes.append(change("propose", cand.value, cand.display, cand.verified, cand.reason, cand.create))
    return changes


def plan_document(config: Config, ex: Extraction, doc: DocumentSnapshot,
                  taxonomy: Taxonomy, correspondent_aliases: dict[str, str],
                  confirm_address: Callable[[], str | None], mode: str) -> Plan:
    """Pure decision: extraction + current document state -> plan."""
    access = FieldAccess(config, taxonomy)
    candidates, info, review = build_candidates(
        config, ex, doc, taxonomy, access, correspondent_aliases, confirm_address, mode)
    changes = decide(config, candidates, doc, access, mode)
    return Plan(doc.id, mode, ex.kind, changes, info,
                review or any(not c.verified for c in changes))


def note_text(plan: Plan, model: str, mode_label: str, apply_tag: str) -> str:
    lines = [f"AI extraction ({model}, {mode_label})"]
    if plan.proposals:
        lines.append(f'Proposed changes - add the tag "{apply_tag}" to accept all, or edit manually:')
        for c in plan.proposals:
            flag = f" [{c.reason}]" if c.reason else ""
            lines.append(f'- {LABELS[c.field]}: "{c.current_display}" -> "{c.display}"{flag}')
    if plan.fills:
        lines.append("Filled automatically: " + ", ".join(
            f'{LABELS[c.field]} "{c.display}"' for c in plan.fills))
    for item in plan.info:
        lines.append(f"Note: {item}")
    return "\n".join(lines)
