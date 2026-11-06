# Changelog

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
