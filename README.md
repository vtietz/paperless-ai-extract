# paperless-ai-extract

[![CI](https://github.com/vtietz/paperless-ai-extract/actions/workflows/ci.yml/badge.svg)](https://github.com/vtietz/paperless-ai-extract/actions/workflows/ci.yml)

A small sidecar container that lets a local or remote LLM fill in metadata for
[Paperless-ngx](https://docs.paperless-ngx.com/) documents. It can read the
**page image** (vision models), the OCR text, or both. It works only through
the Paperless REST API: no patches, no mounted Paperless source, no extra web UI.

It is deliberately **conservative**:

- **Doesn't overwrite.** Empty fields are filled. Values that are already set,
  including your manual corrections, only get a *proposal*. Each field is
  checked again immediately before writing. Paperless has no conditional
  updates, so an edit made in the same instant can still lose; this is a
  check, not a lock.
- **Review happens inside Paperless.** Proposals appear as a document note
  and a tag. Adding the tag `AI: apply` accepts the proposal from the latest
  note. If the document is re-analysed first, the accept tag is removed and
  you review the new proposal.
- **Your lists stay yours.** Correspondents and document types are managed in
  Paperless. New correspondents are created when backed by OCR evidence;
  new document types are proposed by default. Both policies are configurable.
- **Fail-closed evidence checks.** New correspondents, dates, journal names and
  addressees must be backed by the document text. Otherwise they become a
  proposal, not a fill.
- **One engine for import and re-analysis.** A Paperless workflow tags new
  documents. Adding the same tag by hand re-analyses a document.

It extracts the following; everything except the first three is optional:

| Field | Notes |
|---|---|
| title, correspondent, document type | The model sees your document types and the correspondents that appear in the document (a shortlist), and picks the best fit; answers are matched again (aliases, exact, fuzzy). A new correspondent is **created** when its name appears in the OCR text, otherwise **proposed** and created only when you accept it; new document types are proposed (both configurable: create, propose, never). |
| tags | Chosen **only from existing tags** (optionally an allowlist), added and never removed. |
| document date | Proposed by default, or set on the first analysis when the date is printed. |
| addressee / recipient | A select custom field (e.g. household member), validated against the printed addressee or certificate holder name. Configurable aliases and locale rules, plus an optional second OCR reading of the address window. |
| articles | Authors (custom field), journal as correspondent, and publication year as the date. |

Storage paths are left to Paperless: give your library one scheme with
`PAPERLESS_FILENAME_FORMAT`, and handle exceptions with a Paperless workflow,
e.g. *document type is "Article" → storage path "Articles"* (see
[configuration](docs/configuration.md#storage-paths)).

### Why a separate extractor instead of built-in AI?

This project grew out of a household deployment where Paperless's built-in AI
suggestions did not meet the extraction requirements. The reasons were:

- **Page layout matters.** The built-in suggestion pipeline we tested used OCR
  text. Reading the page image also helps distinguish the issuer, addressee,
  certificate holder and dates near signatures or stamps. OCR still provides
  independent text evidence; vision does not make recognition infallible.
- **Custom filing metadata.** We needed a household Recipient custom field,
  name aliases, certificate-holder rules and article authors/publication years,
  alongside the ordinary title, correspondent and document type. These rules
  are configurable rather than changes to Paperless itself.
- **A small inference budget.** In that CPU-only deployment, a stock suggestion
  request containing OCR text, similar documents and taxonomy reached about
  7,000 tokens and exceeded the configured 4,096-token context. A later request
  through this extractor used about 1,800 prompt tokens and took roughly a minute.
  These are deployment observations, not a general performance benchmark;
  model, input and hardware affect the result.
- **Controlled review without internal overrides.** We wanted the same engine
  for imports and manual re-analysis, OCR-backed evidence checks, and proposals
  that preserve existing metadata. Earlier overrides of Paperless's internal
  prompt templates needed attention on upgrades; the sidecar uses its REST API.

Built-in AI remains a reasonable choice when its fields and review behaviour
meet your needs and the model has enough context and compute. This extractor
adds a service to maintain and does not replace Paperless's chat/search features.
Those features can be evaluated separately; they are not required for extraction.

### How it compares

[paperless-gpt](https://github.com/icereed/paperless-gpt) and
[paperless-ai](https://github.com/clusterzx/paperless-ai) are larger, more
feature-rich projects with their own web UIs (review screens, chat, OCR
pipelines). Choose this project if you want a headless, minimal container whose
review workflow is plain Paperless (notes, tags, workflows), and that leaves
existing metadata alone.

## Quick start: add it to your Paperless Compose stack

1. In Paperless, create a user for the service, e.g. `ai-extract`. Give it these
   permissions:
   - view/change: Document
   - view/add: Correspondent, Document type, Tag, Note
   - view: Custom field

   Create an API token for it (profile menu → API token).
   Documents owned by other users must be shared with this user. Existing
   correspondents, document types, tags and custom fields must also be visible
   to it: sharing a document does not share its metadata objects. For a shared
   household taxonomy, make those entries ownerless, or grant the service user
   object-level access. See [ownership and sharing](docs/configuration.md#ownership-and-sharing).

2. Next to your Paperless `docker-compose.yml`, copy
   [`examples/ai-extract.env.example`](examples/ai-extract.env.example) to
   `ai-extract.env`. Set the token, the LLM endpoint and the model, and
   uncomment any options you want. Keep this file out of Git. Then add the
   service ([`examples/compose.yaml`](examples/compose.yaml)):

```yaml
services:
  # ... webserver, db, broker from your existing paperless-ngx compose file
  ai-extract:
    image: ghcr.io/vtietz/paperless-ai-extract:0.5
    restart: unless-stopped
    depends_on: [webserver]
    env_file: ai-extract.env
    volumes:
      - ai-extract-data:/data         # small cache and proposals
    stop_grace_period: 6m             # let a running request finish

volumes:
  ai-extract-data:
```

   A named volume works out of the box. For a bind mount, create the directory
   first and give it to the container user: `mkdir ai-extract && chown 1000 ai-extract`
   (or set `user:` to the directory's owner).

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

### Alternative: a separate Compose project

The service has no dependency on Paperless's internals, so it can also run as
its own project. This suits independent updates, its own config and data
directory, or a Paperless managed by another tool (Unraid templates, Portainer,
etc.). Both projects then share a Docker network, and `PAPERLESS_URL` uses a
name that resolves on it. See
[`examples/compose.separate.yaml`](examples/compose.separate.yaml).

| | Inside the Paperless project | Separate project |
|---|---|---|
| setup | one service block | shared network + own directory |
| `PAPERLESS_URL` | `http://webserver:8000` | container name or alias on the shared network |
| updates | `docker compose pull ai-extract` in the Paperless project | independent of Paperless |

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

## Coexistence with Paperless's own AI

Paperless-ngx 3.x has its own AI features: the **Suggest** button, automatic
suggestions when opening a document, and document chat. They are independent
of this service. They use only OCR text, their own prompt and the model set in
`PAPERLESS_AI_LLM_MODEL`, and they don't know about the recipient field or
`AI: …` tags.

On small local setups the stock Suggest prompt can be too large. It includes
similar documents and taxonomy candidates, about 7,000 tokens in practice, so it
fails with *"request exceeds the available context size"* (HTTP 502 "AI backend
rejected the request") or times out. Options:

| Option | Result | Trade-off |
|---|---|---|
| `PAPERLESS_AI_ENABLED=false` | Suggest, auto-suggest and chat are gone; this service fills metadata | No document chat |
| Larger context (`PAPERLESS_AI_LLM_CONTEXT_SIZE` and Ollama `num_ctx`, e.g. 8192+) | Suggest works with stock prompts | Needs RAM for both models; long prompts are slow on CPU and may hit `PAPERLESS_AI_LLM_REQUEST_TIMEOUT` |
| Keep AI on, disable *automatic* suggestions in the UI settings | Chat stays; Suggest only when clicked | Clicking Suggest can still fail on small contexts |
| Custom Paperless prompt templates (bind-mounting files over `paperless_ai/prompts/*.j2`) | Short prompts fit small contexts | Overrides internal files; review on every Paperless upgrade |

With a GPU or a hosted model, leaving both enabled is fine. They share the model
server, so expect queueing when both run at once.

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
