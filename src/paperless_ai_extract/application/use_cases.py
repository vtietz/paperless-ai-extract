"""Use cases: analyse a document, apply a stored proposal, record a failure.

Depends only on ports and the domain; adapters are injected.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field

from .. import __version__
from ..config import Config, ConfigError
from ..domain.errors import ExtractError, UnsupportedInput
from ..domain.evidence import confirmed_joint_address
from ..domain.matching import compact
from ..domain.models import Change, DocumentSnapshot, Extraction, Item, Plan, Taxonomy
from ..domain.messages import Messages
from ..domain.planner import (DIRECT_FIELDS, FieldAccess, note_text, plan_document,
                              selectable_tags)
from ..domain.prompt import render_instructions, with_document_text
from ..domain.schema import build_schema, parse_extraction
from ..ports import AddressReader, DocumentStore, LLMClient, PageRenderer, StateStore

log = logging.getLogger("paperless_ai_extract")

TAG_ROLES = ("pending", "apply", "proposal", "review", "error")


@dataclass
class Context:
    """Per-cycle view of taxonomy plus the prompt/schema derived from it."""
    taxonomy: Taxonomy
    access: FieldAccess
    labels: list[str] | None
    tag_names: list[str]
    schema: dict
    instructions: str
    fingerprint: str
    tag_ids: dict[str, int] = field(default_factory=dict)


@dataclass
class Outcome:
    plan: Plan
    extraction: Extraction
    cached: bool
    metrics: dict
    written: list[Change] = field(default_factory=list)


class MetadataExtractor:
    def __init__(self, config: Config, store: DocumentStore, llm: LLMClient,
                 renderer: PageRenderer, address_reader: AddressReader, state: StateStore):
        self.config = config
        self.store = store
        self.llm = llm
        self.renderer = renderer
        self.address_reader = address_reader
        self.state = state
        self.aliases = config.correspondent_aliases()
        path = config.extraction.prompt_file
        self.template = path.read_text() if path else None
        self.msg = Messages(config.policy.notes_language)

    # -- context -----------------------------------------------------------
    def context(self, create_tags: bool | None = None) -> Context:
        config = self.config
        taxonomy = self.store.taxonomy()
        access = FieldAccess(config, taxonomy)
        labels = None
        rc = config.extraction.recipient
        if rc.enabled:
            if not access.recipient_field:
                raise ConfigError(f"custom field {rc.custom_field!r} not found")
            labels = list(access.recipient_options())
            if rc.unassigned not in labels:
                raise ConfigError(f"recipient dropdown must contain {rc.unassigned!r}")
            if rc.shared and rc.shared not in labels:
                raise ConfigError(f"recipient dropdown lacks shared option {rc.shared!r}")
        tag_names = ([t.name for t in selectable_tags(config, taxonomy)]
                     if config.extraction.tags.enabled else [])
        if config.extraction.tags.enabled and not tag_names:
            log.warning("tag extraction enabled but no selectable tags exist")
        schema = build_schema(config.extraction, labels, tag_names)
        instructions = render_instructions(config, self.template, labels, tag_names)
        fingerprint = hashlib.sha256(json.dumps({
            "engine": __version__, "llm": self.llm.describe(),
            "input": config.input.model_dump(mode="json"),
            "schema": schema, "instructions": instructions,
        }, sort_keys=True, default=str).encode()).hexdigest()[:16]
        create = config.queue.create_missing_tags if create_tags is None else create_tags
        return Context(taxonomy, access, labels, tag_names, schema, instructions, fingerprint,
                       self._tags(taxonomy, create))

    def _tags(self, taxonomy: Taxonomy, create: bool) -> dict[str, int]:
        names = self.config.queue.tags.model_dump()
        result = {}
        for role in TAG_ROLES:
            name = names.get(role)
            if not name:
                continue
            item = next((t for t in taxonomy.tags if t.name == name), None)
            if item is None and create:
                item = self.store.create_object("tags", name)
                taxonomy.tags.append(item)
                log.info("created tag %r", name)
            if item is not None:
                result[role] = item.id
        return result

    # -- analysis ----------------------------------------------------------
    def _extract(self, doc: DocumentSnapshot, ctx: Context, force: bool,
                 download) -> tuple[Extraction, bool, dict]:
        inp = self.config.input
        uses_image = inp.mode in ("image", "image+text")
        uses_text = inp.mode in ("text", "image+text")
        text = doc.content[: inp.text_chars]
        if uses_text and not text.strip():
            raise UnsupportedInput("document has no text content")
        checksum = self.store.checksum(doc.id, inp.source == "original") if uses_image else ""
        source_key = hashlib.sha256(
            f"{checksum}|{text if uses_text else ''}".encode()).hexdigest()[:16]
        if not force:
            cached = self.state.cached(doc.id, source_key, ctx.fingerprint)
            if cached:
                return Extraction.from_dict(cached), True, {}
        images: list[bytes] = []
        if uses_image:
            data, mime = download()
            images = self.renderer.render(data, mime, inp.pages, inp.max_edge)
        prompt = with_document_text(ctx.instructions, text) if uses_text else ctx.instructions
        started = time.monotonic()
        result = self.llm.generate_json(prompt, images, ctx.schema)
        metrics = {**result.metrics, "seconds": round(time.monotonic() - started, 1)}
        extraction = parse_extraction(result.content, self.config.extraction, ctx.labels,
                                      ctx.tag_names)
        self.state.store(doc.id, source_key, ctx.fingerprint, extraction.to_dict(), metrics)
        return extraction, False, metrics

    def analyse(self, doc_id: int, ctx: Context, *, force: bool = False,
                mode: str | None = None) -> Outcome:
        """Extract and plan without writing anything to the document store."""
        doc = self.store.document(doc_id)
        mode = mode or ("rerun" if self.state.has_succeeded(doc_id) else "first_run")
        files: dict = {}
        original = self.config.input.source == "original"

        def download():
            if "file" not in files:
                files["file"] = self.store.download(doc_id, original)
            return files["file"]

        def confirm_address() -> str | None:
            rc = self.config.extraction.recipient
            if not rc.address_window.enabled:
                return None
            readings = self.address_reader.read(download()[0])
            return (confirmed_joint_address(readings, rc.aliases, rc.address_rules)
                    if readings else None)

        extraction, cached, metrics = self._extract(doc, ctx, force, download)
        plan = plan_document(self.config, extraction, doc, ctx.taxonomy, self.aliases,
                             confirm_address, mode)
        return Outcome(plan, extraction, cached, metrics)

    # -- writing -----------------------------------------------------------
    def _ensure_object(self, endpoint: str, name: str, ctx: Context) -> int:
        items: list[Item] = getattr(ctx.taxonomy, endpoint)
        existing = next((i for i in items if compact(i.name) == compact(name)), None)
        if existing:
            return existing.id
        item = self.store.create_object(endpoint, name)
        items.append(item)
        log.info("created %s %r", endpoint, item.name)
        return item.id

    def _write(self, doc_id: int, changes: list[Change], ctx: Context) -> list[Change]:
        """Write only changes whose field still holds the expected value."""
        fresh = self.store.document(doc_id)
        direct: dict = {}
        custom: dict = {}
        add_tags: list[int] = []
        written = []
        for ch in changes:
            if ch.field == "tags":   # additive: nothing to overwrite, nothing to check
                missing = [t for t in ch.value if t not in fresh.tags and t not in add_tags]
                if missing:
                    add_tags += missing
                    written.append(ch)
                continue
            expected = ch.current if ch.action == "fill" else ch.expect
            if ctx.access.current(fresh, ch.field) != expected:
                log.info("document %s: %s changed meanwhile, skipped", doc_id, ch.field)
                continue
            value = self._ensure_object(*ch.create, ctx) if ch.create else ch.value
            if ch.field in DIRECT_FIELDS:
                direct[ch.field] = value
            else:
                custom[ctx.access.custom_field_id(ch.field)] = value
            written.append(ch)
        self.store.update_document(doc_id, direct)
        self.store.set_custom_fields(doc_id, custom)
        self.store.modify_tags(doc_id, add_tags, [])
        return written

    def _note(self, doc_id: int, text: str):
        if self.config.policy.notes != "never":
            self.store.add_note(doc_id, text)

    def process(self, doc_id: int, ctx: Context, *, force: bool = False,
                mode: str | None = None) -> Outcome:
        """Analyse, fill eligible fields, record proposals, update queue tags."""
        outcome = self.analyse(doc_id, ctx, force=force, mode=mode)
        plan = outcome.plan
        outcome.written = self._write(doc_id, plan.fills, ctx)
        tags = ctx.tag_ids
        add = []
        remove = [tags[r] for r in ("pending", "error") if r in tags]
        if plan.proposals:
            self.state.save_proposal(doc_id, [c.to_dict() for c in plan.proposals])
            add += [tags["proposal"]] if "proposal" in tags else []
        else:
            self.state.drop_proposal(doc_id)
            remove += [tags["proposal"]] if "proposal" in tags else []
        if "review" in tags:
            (add if plan.review else remove).append(tags["review"])
        policy = self.config.policy.notes
        if policy == "always" or (policy == "proposals" and (plan.proposals or plan.info)):
            self._note(doc_id, note_text(plan, self.config.llm.model, self.msg,
                                         self.config.queue.tags.apply))
        self.store.modify_tags(doc_id, add, remove)
        self.state.success(doc_id)
        log.info("document %s: %s, filled %s, proposed %s%s", doc_id, plan.mode,
                 [c.field for c in outcome.written], [c.field for c in plan.proposals],
                 " (cached extraction)" if outcome.cached else "")
        return outcome

    def apply_proposal(self, doc_id: int, ctx: Context) -> list[Change]:
        tags = ctx.tag_ids
        remove = [tags[r] for r in ("apply", "proposal") if r in tags]
        stored = self.state.proposal(doc_id)
        if not stored:
            self._note(doc_id, self.msg("no_proposal"))
            self.store.modify_tags(doc_id, [], remove)
            return []
        changes = [Change.from_dict(c) for c in stored]
        written = self._write(doc_id, changes, ctx)
        skipped = [c for c in changes if c not in written]
        labels = self.msg.labels
        lines = [self.msg("applied", items=", ".join(
            f'{labels[c.field]} "{c.display}"' for c in written) or self.msg("nothing"))]
        if skipped:
            lines.append(self.msg("skipped", items=", ".join(labels[c.field] for c in skipped)))
        self._note(doc_id, "\n".join(lines))
        self.store.modify_tags(doc_id, [], remove)
        self.state.drop_proposal(doc_id)
        log.info("document %s: applied %s, skipped %s", doc_id,
                 [c.field for c in written], [c.field for c in skipped])
        return written

    def record_failure(self, doc_id: int, exc: ExtractError, ctx: Context) -> bool:
        """Count a failure; give up (error tag, note) when permanent or exhausted."""
        message = f"{exc.__class__.__name__}: {exc}"
        attempts = self.state.failure(doc_id, message, self.config.queue.retry_delay)
        log.warning("document %s: attempt %s failed: %s", doc_id, attempts, message)
        if exc.retryable and attempts < self.config.queue.max_attempts:
            return False
        tags = ctx.tag_ids
        self._note(doc_id, self.msg("gave_up", attempts=attempts, error=message[:300],
                                    pending=self.config.queue.tags.pending))
        self.store.modify_tags(doc_id, [tags["error"]] if "error" in tags else [],
                               [tags["pending"]])
        self.state.reset_attempts(doc_id)
        return True
