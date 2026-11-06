# Changelog

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
