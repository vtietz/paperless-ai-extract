# Architecture

Ports-and-adapters ("clean architecture"). Dependencies point inwards only.

```
cli.py ──▶ bootstrap.py (composition root: the only module that imports adapters)
                 │
                 ▼
application/   use_cases.MetadataExtractor   analyse · process · apply_proposal · record_failure
               worker.QueueWorker            tag polling, retries, heartbeat, graceful stop
                 │ depends on
                 ▼
ports.py       DocumentStore · LLMClient · PageRenderer · AddressReader · StateStore
domain/        models · schema · prompt · matching · evidence · planner   (pure, no I/O)
                 ▲ implemented by
adapters/      paperless.PaperlessClient          REST API v10
               llm.OllamaClient / OpenAICompatibleClient
               rendering.PopplerPillowRenderer    pdftoppm / Pillow
               address_ocr.TesseractAddressReader
               sqlite_state.SqliteStateStore
config.py      pydantic settings (plain value objects, shared by all layers)
```

## Domain

- `schema` builds the JSON schema sent to the model (property order follows the
  validated pilot) and parses the answer strictly; violations raise `ExtractionError`.
- `prompt` renders the operator's prompt template (`string.Template` placeholders).
  Document text is appended in a delimited block, never templated.
- `matching` resolves names: alias → exact normalized (unowned first) → difflib
  fuzzy match with Paperless's native threshold.
- `evidence` contains the fail-closed rules: addressee quote must occur in the OCR
  text and support the chosen person(s); joint aliases count only as a standalone
  postal address line; multiple OCR readings must agree.
- `planner.plan_document` is the single decision function:
  extraction + current document → `Plan` of `fill`/`propose` changes.

## Application

`MetadataExtractor.process` = `analyse` (extract with cache, plan) → write fills
with an optimistic check (a field is written only if it still holds the value seen
while planning) → store proposals → note → tags → mark success.
`apply_proposal` writes stored proposals under the same check against the value
expected after the analysis.

Errors derive from `domain.errors.ExtractError`; `retryable` decides between
backoff (`queue.retry_delay × attempts`) and giving up (`error` tag + note).

## State

SQLite at `state.path`: extraction cache, run history (first vs re-run), retry
counters and open proposals. Losing it is safe: documents are re-analysed and
treated as first runs, which still only fill empty fields.

## Extension points

| Want | Do |
|---|---|
| another LLM API | implement `ports.LLMClient`, register in `adapters/llm/__init__.py` |
| another document system | implement `ports.DocumentStore` |
| different rendering (e.g. pdfium) | implement `ports.PageRenderer` |
| another field | add to `Extraction`, `schema`, `planner.build_candidates`, `FieldAccess` |

## Tests

`tests/` uses in-memory fakes for all ports (`conftest.py`) and
`httpx.MockTransport` for HTTP adapters. Poppler/Tesseract tests run in the
`test` Docker stage, where the tools are installed.
