# Changelog

## 0.5.0 — 2026-11-08

- **Behaviour change:** `taxonomy.new_correspondents` now defaults to `create`.
  A new sender is created and set when its name occurs in the OCR text
  (`new_correspondent_requires_text_evidence`, default `true`); otherwise it is
  only proposed as before. Set `new_correspondents: propose` to keep the 0.3/0.4
  behaviour. `new_document_types` stays `propose`.

## 0.4.0 — 2026-11-07

- **Removed:** storage path handling (`taxonomy.storage_paths`, policy field
  `storage_path`). Use `PAPERLESS_FILENAME_FORMAT` for the general scheme and a
  Paperless workflow (filter by document type, assign storage path) for
  exceptions; it is visible and editable in Paperless and also runs on manual
  changes. Old configs with `storage_paths` fail with an explanatory message.
  The service user no longer needs to view storage paths.

## 0.3.0 — 2026-11-07

- Correspondent shortlist: existing correspondents whose name (or alias) occurs
  in the document's OCR text are listed in the prompt (`extraction.correspondents`,
  `offer: shortlist|all|none`, `max_listed: 15`). New placeholder
  `${correspondent_options}`.
- New entries are proposed by default: `taxonomy.new_correspondents` and
  `new_document_types` (`propose` | `create` | `never`, default `propose`). A
  proposed entry is created when the proposal is accepted. **Behaviour change:**
  0.1/0.2 created new correspondents and types right away; set `create` to keep
  that. The old `create_*` booleans are still accepted.

## 0.2.0 — 2026-11-06

- The model now sees the existing document types and picks the best fit
  (`extraction.document_types`, on by default; `excluded`, `max_listed`). It names
  a new type only when `taxonomy.create_document_types` is true; when false, the
  answer is restricted to the listed types by the JSON schema.
- `taxonomy.document_type_aliases` maps names the model uses to an existing type.
- Custom prompts: new placeholder `${document_type_options}`. Prompts that don't
  use it (and don't use `${field_instructions}`) behave as before.
- Changing the document types changes the prompt, so cached extractions are not
  reused for documents queued again afterwards.

## 0.1.1 — 2026-11-06

Fixes from an external review:

- Re-analysis removes a pending `AI: apply` tag, so an old acceptance can no
  longer approve a new, unreviewed proposal; the note says so.
- Write guard re-reads the document after creating correspondents or document
  types, right before writing. Still a check, not a lock: Paperless has no
  conditional updates. Documentation no longer says "never overwrites".
- Model answers missing required fields (e.g. `{}` from backends without
  schema enforcement) are rejected and retried instead of completing the document.
- Textual dates ("12. März 2025", "March 12, 2025") must match the month.
- Documents in retry backoff no longer block newer queued documents.
- Examples use a named volume; bind mounts need `chown 1000` (documented).

## 0.1.0 — 2026-11-06

First public version.

- Tag-driven queue (`AI: pending` / `AI: apply`) with fill-empty / propose policy,
  notes in English or German, retries and error tag.
- Extraction from page images, OCR text or both; Ollama and OpenAI-compatible backends.
- Title, correspondent, document type, storage path by kind, tags from existing
  tags, document date, select-field recipient with evidence checks and optional
  address-window OCR, article profile (authors, journal, year).
- Built-in prompt; configuration by environment variables or YAML.
- Container image for linux/amd64 and linux/arm64; `examples/ai-extract.env.example`
  documents every environment variable.
