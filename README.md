# paperless-ai-extract

Metadata extraction for [Paperless-ngx](https://docs.paperless-ngx.com/) with a
local or remote LLM, from **page images**, OCR text, or both. It runs as a
separate service that talks to Paperless only through its **REST API**. No
Paperless source files are patched or mounted.

What it extracts (each part is optional and configured per installation):

- title, correspondent, document type, and storage path by document kind
- a select-type custom field such as a household **Recipient**, with fail-closed
  evidence checks and an optional second OCR reading of the address window
- for articles: authors (long-text custom field), the journal as correspondent,
  and the publication year as the created date

## How it works

```
Paperless workflow "Document Added" ──assign tag──▶  AI: pending
                       user adds tag manually ──────▶  AI: pending   (re-analyse)
                                                           │
                                       paperless-ai-extract polls the tag
                                                           ▼
             download archive PDF ─▶ render page(s) ─▶ LLM (structured JSON)
                                                           ▼
                     validate evidence ─▶ plan: fill empty fields / propose others
                                                           ▼
                   PATCH fields, note with proposals, tags AI: proposal / AI: review
                                                           │
                     user adds AI: apply ──▶ stored proposal applied (if field unchanged)
```

One engine and one rule set serve both import and manual re-analysis:

| Situation | Default behaviour |
|---|---|
| First analysis, field empty, evidence OK | **fill** |
| First analysis, field empty, evidence failed | fill a safe fallback (for example `Unassigned`) and **propose** the value |
| Field already set (manually or earlier) | **propose** only; never overwritten |
| Later re-analysis (`policy.rerun: propose`) | **propose** only |
| Storage path | fill when empty; never proposed |

An "empty" title means blank, or still equal to the uploaded file name.
Proposals are written as a Paperless note and stored locally. Adding the
`apply` tag accepts them. If the user edited a proposed field in the meantime,
that field is skipped.

Extraction results are cached by file checksum and engine fingerprint (model,
prompt, schema, input settings). Re-queuing an unchanged document costs no
inference.

Paperless's own "Suggest" button is unaffected. It remains Paperless's native,
text-only AI feature.

## Quick start

1. In Paperless, create an API user. A non-superuser is enough when documents
   and taxonomy are unowned or shared with it. It needs:
   - view/change on documents
   - view/add on correspondents, document types and tags
   - view on storage paths and custom fields
   - add on notes

   Then create its API token.
2. Copy `examples/config.minimal.yaml` (or `examples/household/`) into a config
   directory, adapt it, and write the prompt file.
3. Run:

```sh
docker build -t paperless-ai-extract .
docker run --rm -v $PWD/config:/config:ro -v $PWD/data:/data \
  -e PAPERLESS_TOKEN=... paperless-ai-extract check --create-tags
docker run --rm -v $PWD/config:/config:ro -v $PWD/data:/data \
  -e PAPERLESS_TOKEN=... paperless-ai-extract analyse 123     # dry run, prints the plan
```

4. Deploy with `examples/compose.yaml` (command `serve`).
5. In Paperless, create a workflow (trigger *Document Added*) that assigns the
   `AI: pending` tag.

## Commands

| Command | Purpose |
|---|---|
| `check [--create-tags]` | check Paperless auth, LLM/model, custom fields, tags and OCR tools |
| `analyse ID… [--force] [--mode first_run\|rerun]` | dry run: print extraction and plan as JSON, **no writes** |
| `process ID… [--force]` | process now, exactly as the queue would |
| `serve [--once]` | run the tag-driven queue worker |
| `health` | exit 0 if the worker heartbeat is fresh (container healthcheck) |

## LLM backends

| `llm.provider` | Endpoint | Works with |
|---|---|---|
| `ollama` | `POST {base_url}/api/chat`, schema via `format`, images base64 | Ollama |
| `openai` | `POST {base_url}/chat/completions`, `response_format: json_schema`, images as data URLs | OpenAI, vLLM, llama.cpp server, LM Studio, LocalAI, LiteLLM, Ollama `/v1` |

`llm.options` is passed through: as Ollama `options`, or as extra body fields
such as `temperature`/`max_tokens` for OpenAI-compatible servers. For servers
without JSON-schema support, set `structured_output` to `json_object` or `none`.

To add a backend, implement `ports.LLMClient` and register the class in
`adapters/llm/__init__.py`.

## Configuration

See [docs/configuration.md](docs/configuration.md). Values support `${ENV}` and
`${ENV:-default}`. Secrets can be read from files via `token_file` /
`api_key_file`.

## Development

```sh
docker build --target test -t paperless-ai-extract:test . && docker run --rm paperless-ai-extract:test
```

Architecture and extension points: [docs/architecture.md](docs/architecture.md).

## Limitations

- Image mode analyses only the first `input.pages` pages.
- Evidence rules are string checks against Paperless's OCR text. With
  image-only extraction, values the OCR missed become proposals, not fills.
- The address-window check supports only configured multi-person aliases on
  portrait letters with a conventional upper-left address window. It uses two
  Tesseract layout modes; it is not an independent confidence score.
- Import latency is the polling interval (default 30 s) plus inference time.
