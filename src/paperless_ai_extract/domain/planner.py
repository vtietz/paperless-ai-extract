"""Turn an extraction into a reviewable plan: what to fill, what to propose.

Rules (one engine for import and manual reruns):
  * A value is a *candidate* when it resolves to a usable Paperless value.
  * A candidate is *verified* unless an evidence rule failed.
  * Empty field + fill policy + verified          -> fill.
  * Empty field + fill policy + unverified        -> fill the safe fallback
                                                     (if any) and propose the value.
  * Non-empty field, or propose policy             -> propose (never overwrite).
  * Storage path is only ever filled when empty, never proposed.
  * Tags are only ever added, never removed.
"""
from __future__ import annotations

from pathlib import PurePath
from typing import Callable

from ..config import Config
from .evidence import date_supported, occurs_in, validated_recipient
from .matching import apply_alias, find
from .messages import Messages
from .models import Candidate, Change, DocumentSnapshot, Extraction, Item, Plan, Taxonomy

DIRECT_FIELDS = {"title", "correspondent", "document_type", "storage_path", "created"}
NEVER_PROPOSE = {"storage_path"}


def selectable_tags(config: Config, taxonomy: Taxonomy) -> list[Item]:
    """Tags the model may choose: never inbox or queue tags."""
    tags_cfg = config.extraction.tags
    reserved = {n for n in config.queue.tags.model_dump().values() if n} | set(tags_cfg.excluded)
    usable = [t for t in taxonomy.tags if not t.inbox and t.name not in reserved]
    if tags_cfg.allowed:
        wanted = set(tags_cfg.allowed)
        usable = [t for t in usable if t.name in wanted]
    return sorted(usable, key=lambda t: t.name.casefold())


def selectable_document_types(config: Config, taxonomy: Taxonomy) -> list[str]:
    """Existing document types offered to the model ([] = not listed)."""
    cfg = config.extraction.document_types
    if not cfg.offer_existing:
        return []
    excluded = set(cfg.excluded)
    names = sorted({t.name for t in taxonomy.document_types if t.name not in excluded},
                   key=str.casefold)
    return names if len(names) <= cfg.max_listed else []


class FieldAccess:
    """Read current values of the logical fields from a snapshot."""

    def __init__(self, config: Config, taxonomy: Taxonomy):
        self.config = config
        self.taxonomy = taxonomy
        self.msg = Messages(config.policy.notes_language)
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
        if name == "tags":
            return list(doc.tags)
        if name in DIRECT_FIELDS:
            return getattr(doc, name)
        field_id = self.custom_field_id(name)
        return doc.custom_fields.get(field_id) if field_id is not None else None

    def display(self, name: str, value) -> str:
        if value in (None, "", []):
            return self.msg("empty")
        if name == "tags":
            return ", ".join(self.taxonomy.name_of("tags", i) or "" for i in value)
        if name in ("correspondent", "document_type", "storage_path"):
            return self.taxonomy.name_of(name + "s", value) or self.msg("empty")
        if name == "recipient":
            for label, option_id in self.recipient_options().items():
                if option_id == value:
                    return label
        return str(value)

    def is_empty(self, doc: DocumentSnapshot, name: str) -> bool:
        if name == "title":
            stem = PurePath(doc.original_file_name or "").stem
            return not doc.title.strip() or (
                self.config.policy.title_empty_if_filename and bool(stem) and doc.title == stem)
        if name == "tags":
            return True       # adding tags never overwrites anything
        if name == "created":
            return False      # Paperless always sets a date; see treat_as_empty
        return self.current(doc, name) in (None, "")


def build_candidates(config: Config, ex: Extraction, doc: DocumentSnapshot,
                     taxonomy: Taxonomy, access: FieldAccess,
                     correspondent_aliases: dict[str, str],
                     confirm_address: Callable[[], str | None],
                     mode: str) -> tuple[list[Candidate], list[str], bool]:
    msg = access.msg
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
            cand = Candidate("correspondent", None, msg("new", name=name),
                             create=("correspondents", name))
            if tax_cfg.new_correspondent_requires_text_evidence and not (
                    occurs_in(name, content) or occurs_in(ex.correspondent, content)):
                cand.verified, cand.reason = False, msg("reason_new_name")
        else:
            cand = Candidate("correspondent", None, msg("new", name=name),
                             create=("correspondents", name),
                             verified=False, reason=msg("reason_creation_disabled"))
        if article_evidence and cand.verified and not (
                occurs_in(ex.correspondent, content) or occurs_in(name, content)):
            cand.verified, cand.reason = False, msg("reason_publication")
        candidates.append(cand)

    if ex.document_type:
        type_name = apply_alias(ex.document_type, tax_cfg.document_type_aliases)
        match = find(type_name, taxonomy.document_types, tax_cfg.fuzzy_threshold)
        if match:
            candidates.append(Candidate("document_type", match.id, match.name))
        else:
            allowed = tax_cfg.create_document_types
            candidates.append(Candidate(
                "document_type", None, msg("new", name=type_name),
                create=("document_types", type_name), verified=allowed,
                reason="" if allowed else msg("reason_creation_disabled")))

    path_name = tax_cfg.storage_paths.get(ex.kind)
    if path_name:
        path = find(path_name, taxonomy.storage_paths, 1.0)
        if path:
            candidates.append(Candidate("storage_path", path.id, path.name))
        else:
            info.append(msg("info_storage_path", name=path_name))

    if ex.tags:
        by_name = {t.name: t for t in selectable_tags(config, taxonomy)}
        new = [by_name[n] for n in ex.tags if n in by_name and by_name[n].id not in doc.tags]
        if new:
            candidates.append(Candidate("tags", [t.id for t in new],
                                        msg("added", names=", ".join(t.name for t in new))))

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
                info.append(msg("info_recipient_window", name=confirmed))
        if chosen != rc.unassigned or ex.recipient == rc.unassigned:
            candidates.append(Candidate("recipient", options[chosen], chosen))
            if chosen == rc.unassigned:
                info.append(msg("info_recipient_unknown"))
                review = True
        else:
            quote = " ".join(ex.addressee_text.split())[:120]
            candidates.append(Candidate(
                "recipient", options[ex.recipient], ex.recipient, verified=False,
                reason=msg("reason_addressee", quote=quote),
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
                info.append(msg("info_authors_missing", names="; ".join(missing)))
                review = True
        else:
            joined = "; ".join(ex.authors)
            candidates.append(Candidate("authors", joined, joined, verified=False,
                                        reason=msg("reason_authors")))

    current_date = doc.created[:10] if doc.created else None
    if is_article and articles.created_from_year and ex.publication_year:
        year = ex.publication_year
        current_year = int(current_date[:4]) if current_date and current_date[:4].isdigit() else None
        if current_year != year:
            value = f"{year}-01-01"
            verified = not articles.require_text_evidence or str(year) in content
            # Only the first bibliography pass may initialise the date from a year.
            first_pass = mode == "first_run" and (
                access.authors_field is None or access.authors_field["id"] not in doc.custom_fields)
            candidates.append(Candidate("created", value, value, verified=verified,
                                        reason="" if verified else msg("reason_year"),
                                        treat_as_empty=first_pass))
    elif config.extraction.document_date.enabled and ex.document_date \
            and ex.document_date != current_date:
        verified = date_supported(ex.document_date, content)
        fill = config.extraction.document_date.first_run == "fill" and mode == "first_run"
        candidates.append(Candidate("created", ex.document_date, ex.document_date,
                                    verified=verified,
                                    reason="" if verified else msg("reason_date"),
                                    treat_as_empty=fill))

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

        empty = (cand.treat_as_empty if cand.treat_as_empty is not None
                 else access.is_empty(doc, cand.field))
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


def note_text(plan: Plan, model: str, msg: Messages, apply_tag: str) -> str:
    labels = msg.labels
    lines = [msg("header", model=model, mode=msg(plan.mode))]
    if plan.proposals:
        lines.append(msg("proposals", apply=apply_tag))
        for c in plan.proposals:
            flag = f" [{c.reason}]" if c.reason else ""
            if c.field == "tags":
                lines.append(f"- {labels['tags']}: {c.display}{flag}")
            else:
                lines.append(f'- {labels[c.field]}: "{c.current_display}" -> "{c.display}"{flag}')
    if plan.fills:
        lines.append(msg("filled", items=", ".join(
            f'{labels[c.field]} "{c.display}"' for c in plan.fills)))
    for item in plan.info:
        lines.append(msg("note", text=item))
    return "\n".join(lines)
