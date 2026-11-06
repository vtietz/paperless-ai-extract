# paperless-ai-extract

[![CI](https://github.com/vtietz/paperless-ai-extract/actions/workflows/ci.yml/badge.svg)](https://github.com/vtietz/paperless-ai-extract/actions/workflows/ci.yml)

A small sidecar container that lets a local or remote LLM fill in metadata for
[Paperless-ngx](https://docs.paperless-ngx.com/) documents. It can read the
**page image** (vision models), the OCR text, or both. It works only through
the Paperless REST API: no patches, no mounted Paperless source, no extra web UI.

It is deliberately **conservative**:

- **Never overwrites.** Empty fields are filled. Values that are already set,
  including your manual corrections, only get a *proposal*.
- **Review happens inside Paperless.** Proposals appear as a document note
  and a tag. Adding the tag `AI: apply` accepts them.
- **Fail-closed evidence checks.** New correspondents, dates, journal names and
  addressees must be backed by the document text. Otherwise they become a
  proposal, not a fill.
- **One engine for import and re-analysis.** A Paperless workflow tags new
  documents. Adding the same tag by hand re-analyses a document.

It extracts the following; everything except the first three is optional:

| Field | Notes |
|---|---|
| title, correspondent, document type | Matched against your existing taxonomy (aliases, exact, fuzzy). New entries can be created. |
| tags | Chosen **only from existing tags** (optionally an allowlist), added and never removed. |
| document date | Proposed by default, or set on the first analysis when the date is printed. |
| storage path | Chosen by document kind (e.g. `household` / `article`). |
| addressee / recipient | A select custom field (e.g. household member), validated against the address block. Configurable aliases and locale rules, plus an optional second OCR reading of the address window. |
| articles | Authors (custom field), journal as correspondent, and publication year as the date. |

### How it compares

[paperless-gpt](https://github.com/icereed/paperless-gpt) and
[paperless-ai](https://github.com/clusterzx/paperless-ai) are larger, more
feature-rich projects with their own web UIs (review screens, chat, OCR
pipelines). Choose this project if you want a headless, minimal container whose
review workflow is plain Paperless (notes, tags, workflows), and that never
overwrites existing metadata.

## Quick start: add it to your Paperless Compose stack

1. In Paperless, create a user for the service, e.g. `ai-extract`. Give it these
   permissions:
   - view/change: Document
   - view/add: Correspondent, Document type, Tag, Note
   - view: Storage path, Custom field

   Create an API token for it (profile menu → API token).
   *Documents owned by other users must be shared with this user, or use an
   admin account.*

2. Next to your Paperless `docker-compose.yml`, copy
   [`examples/ai-extract.env.example`](examples/ai-extract.env.example) to
   `ai-extract.env`. Set the token, the LLM endpoint and the model, and
   uncomment any options you want. Keep this file out of Git. Then add the
   service ([`examples/compose.yaml`](examples/compose.yaml)):

```yaml
services:
  # ... webserver, db, broker from your existing paperless-ngx compose file
  ai-extract:
    image: ghcr.io/vtietz/paperless-ai-extract:0.1
    restart: unless-stopped
    depends_on: [webserver]
    env_file: ai-extract.env
    volumes:
      - ./ai-extract:/data            # small cache and proposals (uid 1000)
    stop_grace_period: 6m             # let a running request finish
```

   Minimal `ai-extract.env`:

```sh
PAPERLESS_URL=http://webserver:8000
PAPERLESS_TOKEN=...
LLM_PROVIDER=ollama                   # or openai (any OpenAI-compatible API)
LLM_BASE_URL=http://ollama:11434      # openai: e.g. http://vllm:8000/v1
LLM_MODEL=qwen3.5:4b                  # a vision model for the default image mode
PAE__EXTRACTION__TAGS__ENABLED=true   # optional extras: any setting via PAE__SECTION__KEY
```

3. `docker compose up -d ai-extract`. Then run
   `docker compose run --rm ai-extract check`; it creates the five `AI: …` tags.
4. In Paperless, add a workflow: trigger **Document Added**, action
   **Assignment** → tag `AI: pending`.

Try it on an existing document first: add the tag `AI: pending` and wait for
the note. A dry run that writes nothing:
`docker compose run --rm ai-extract analyse <document id>`.

> If you set `PAPERLESS_ALLOWED_HOSTS`, include the host name used in
> `PAPERLESS_URL` (here `webserver`). Don't share your Paperless `env_file`
> with this container: Paperless's own `PAPERLESS_URL` means something else.

## Daily use

| Tag | Meaning |
|---|---|
| `AI: pending` | queue: analyse (added by the workflow, or by you to re-analyse) |
| `AI: proposal` | the note contains proposals |
| `AI: apply` | you: accept all proposals of the latest note |
| `AI: review` | something could not be verified (e.g. no addressee found) |
| `AI: error` | gave up after retries; see the note; re-add `AI: pending` to retry |

| Situation | Behaviour (default policy) |
|---|---|
| first analysis, field empty, evidence OK | **fill** |
| first analysis, field empty, evidence missing | fill a safe fallback if configured, **propose** the value |
| field already set | **propose** only |
| later re-analysis | **propose** only |
| tags | added only, from existing tags |

A proposal is skipped when you edit the field before applying it. Extraction
results are cached by file checksum and engine settings, so re-tagging an
unchanged document costs no new inference.

## Configuration

Environment variables cover simple setups. For anything larger, mount a YAML
file at `/config/config.yaml` (env vars still override it). See
**[docs/configuration.md](docs/configuration.md)** and the
[examples](examples/), including a household profile with a recipient field,
address aliases and articles.

| Variable | Meaning |
|---|---|
| `PAPERLESS_URL`, `PAPERLESS_TOKEN` (`_FILE`) | Paperless API |
| `LLM_PROVIDER` | `ollama` (native API) or `openai` (OpenAI, vLLM, llama.cpp, LM Studio, LocalAI, LiteLLM, …) |
| `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY` (`_FILE`) | model endpoint |
| `INPUT_MODE` | `image` (default), `text` or `image+text` |
| `PAE__…` | any setting, e.g. `PAE__LLM__OPTIONS='{num_ctx: 8192}'` |

A built-in prompt adapts to the enabled fields. Replace it with
`extraction.prompt_file` when needed.

## Commands

| Command | Purpose |
|---|---|
| `serve` | run the queue (default) |
| `check [--create-tags]` | check Paperless, LLM/model, custom fields, tags, OCR tools |
| `analyse ID… [--force] [--mode first_run\|rerun]` | dry run: print extraction and plan as JSON, **no writes** |
| `process ID… [--force]` | process now, exactly like the queue |
| `health` | container healthcheck (worker heartbeat) |

## Hardware notes

Developed on a 4-core NAS with CPU-only Ollama: `qwen3.5:4b` takes about
60–70 s per first-page image (1120 px, about 1,800 prompt tokens). That's fine
for a background queue, but don't expect interactive speed. Text mode with a
small instruct model is faster but less robust on letters and articles.

## Development

```sh
docker build --target test -t paperless-ai-extract:test . && docker run --rm paperless-ai-extract:test
```

Clean architecture: a pure domain (rules, planner), ports, adapters (Paperless,
LLMs, Poppler/Tesseract, SQLite) and a composition root. See
[docs/architecture.md](docs/architecture.md). Contributions welcome. New LLM
backends implement one small interface.

## Limitations

- Image mode analyses only the first `input.pages` pages (default 1).
- Evidence checks compare against Paperless's OCR text. If OCR missed something
  the vision model saw, the value becomes a proposal.
- Address-block rules default to German/English conventions. Other locales
  configure `extraction.recipient.address_rules`.
- No web UI and no chat. Latency is the poll interval plus inference time.

## License

MIT
