# Configuration reference

Settings come from an optional YAML file (`PAE_CONFIG`, default
`/config/config.yaml`) and from environment variables, which override the file.
Without a file, the environment alone is enough. Unknown keys are rejected.
Relative paths are resolved against the file's directory. Inside the file,
`${NAME}` and `${NAME:-default}` are expanded from the environment.

## Environment variables

| Variable | Setting |
|---|---|
| `PAPERLESS_URL` | `paperless.url` |
| `PAPERLESS_TOKEN` / `PAPERLESS_TOKEN_FILE` | `paperless.token` / `paperless.token_file` |
| `LLM_PROVIDER` | `llm.provider` |
| `LLM_BASE_URL` | `llm.base_url` |
| `LLM_MODEL` | `llm.model` |
| `LLM_API_KEY` / `LLM_API_KEY_FILE` | `llm.api_key` / `llm.api_key_file` |
| `INPUT_MODE` | `input.mode` |
| `PAE__<SECTION>__<KEY>[__<SUBKEY>]` | any setting; the value is parsed as YAML |

Examples: `PAE__EXTRACTION__TAGS__ENABLED=true`,
`PAE__EXTRACTION__TAGS__ALLOWED='[Tax, Insurance]'`,
`PAE__LLM__OPTIONS='{num_ctx: 8192, temperature: 0.1}'`.

## All settings with defaults

```yaml
paperless:
  url: http://paperless:8000          # base URL as seen from the service (required)
  token: null                         # or token_file: /run/secrets/paperless_token (required)
  timeout: 60
  verify_tls: true
  headers: {}                         # e.g. {Host: paperless.example.org} if ALLOWED_HOSTS requires it

llm:
  provider: ollama                    # ollama | openai
  base_url: http://ollama:11434       # required; openai: include /v1
  model: qwen3.5:4b                   # required
  api_key: null                       # or api_key_file
  timeout: 300
  options: {}                         # passed through: Ollama "options" / OpenAI body fields
  think: false                        # Ollama only; null omits the flag
  keep_alive: null                    # Ollama only
  structured_output: json_schema      # json_schema | json_object | none
  headers: {}

input:
  mode: image                         # image | text | image+text
  pages: 1                            # pages rendered for image modes
  max_edge: 1120                      # longest image edge in pixels
  text_chars: 4000                    # OCR characters for text modes
  source: archive                     # archive (OCRed PDF) | original

extraction:
  prompt_file: null                   # null = built-in prompt; see placeholders below
  kinds: [document]                   # e.g. [household, article]
  title_max_length: 128
  language: null                      # e.g. German; null = language of the document
  tags:
    enabled: false
    allowed: []                       # tag names; empty = all except inbox and queue tags
    excluded: []
    max_tags: 3
  document_types:                     # existing types offered to the model
    offer_existing: true              # list them in the prompt; the model picks the best fit
    excluded: []                      # type names never offered
    max_listed: 150                   # more types than this: not listed (prompt size)
  document_date:
    enabled: false
    first_run: propose                # propose | fill (fill only when the date is printed)
  recipient:                          # optional select custom field for the addressee
    enabled: false
    custom_field: Recipient
    unassigned: Unassigned            # must exist in the dropdown
    shared: null                      # optional option for household-wide documents
    shared_keywords: []               # words that must appear in the addressee quote
    aliases: {}                       # "Canonical label": ["printed variant", ...]
    address_rules:                    # locale rules for postal address blocks
      postal_code: '\b(?:D[ -]*)?\d{5}\s*[^\W\d_]'
      street_number: '\d+[a-z]?\s*$'
      salutations: [Frau, Herr, Herrn, Familie, Mr, Mrs, Ms, Mx]
      sender_labels: [Absender, Auftraggeber, Sender, From]
      name_joiners: ["&", und, and]
    address_window:
      enabled: false                  # second OCR reading for joint aliases (portrait PDFs)
      languages: deu+eng              # installed Tesseract languages (image build arg)
      psm_modes: ["6", "11"]
      scale_to: 2400
      x: 0
      y: 240
      width: 1100
      height: 600                     # window in pixels at scale_to (DIN 5008 letters)
      min_aspect: 1.2
      max_aspect: 1.8
  articles:
    enabled: false
    kind: article                     # must be listed in kinds
    authors_field: Authors            # long-text custom field
    created_from_year: true
    require_text_evidence: true       # journal, authors and year must be in the OCR text

taxonomy:
  correspondent_aliases: {}           # printed/model name -> existing correspondent, e.g. {"Telekom": "Telekom Deutschland GmbH"}
  correspondent_aliases_file: null    # JSON object with the same shape
  document_type_aliases: {}           # model name -> existing type, e.g. {"Slide deck": "Presentation"}
  create_correspondents: true         # created unowned (shared), like Paperless's AI workflow
  create_document_types: true         # false: the model may only choose listed types
  new_correspondent_requires_text_evidence: true
  fuzzy_threshold: 0.8                # difflib cutoff; >= 1 disables fuzzy matching
  storage_paths: {}                   # kind: "Storage path name" (only when empty)

policy:
  fields: [title, correspondent, document_type, storage_path, created, recipient, authors, tags]
  first_run: fill_empty               # fill_empty | propose
  rerun: propose                      # fill_empty | propose
  title_empty_if_filename: true
  notes: proposals                    # always | proposals | never
  notes_language: en                  # en | de

queue:
  poll_interval: 30
  batch_size: 10
  max_attempts: 3
  retry_delay: 300                    # seconds × attempt number
  create_missing_tags: true
  tags:
    pending: "AI: pending"
    apply: "AI: apply"
    proposal: "AI: proposal"          # null disables
    review: "AI: review"              # null disables
    error: "AI: error"                # null disables

state:
  path: /data/state.sqlite3
  heartbeat_file: /data/heartbeat
```

## Prompt

The built-in prompt lists instructions only for the enabled fields. It is a
good start for most setups. A custom `prompt_file` uses Python
`string.Template` syntax:

| Placeholder | Value |
|---|---|
| `${field_instructions}` | the built-in instructions for all enabled fields |
| `${source_description}` | for example "attached first-page image", "OCR text" |
| `${input_hint}` | layout hint for image modes, empty for text |
| `${kinds}` | JSON list of `extraction.kinds` |
| `${tag_options}` | JSON list of selectable tags |
| `${document_type_options}` | JSON list of existing document types offered to the model |
| `${recipient_options}` | JSON list of dropdown labels |
| `${recipient_aliases}` | `Alias: printed => canonical` lines |

The model returns JSON with the fields `kind`, `authors`, `publication_year`,
`title`, `correspondents` (0–1), `document_types` (0–1), `tags`,
`document_date`, `addressee_text` and `recipient`. Each field is present only
when its feature is enabled. Tags are an enum of the selectable tags; unknown
tags are dropped. Document types are an enum of the listed types only when
`create_document_types` is false; otherwise the model may name a new type,
which is matched (alias, exact, fuzzy) and created only if nothing matches.

## Locale rules for addresses

The recipient check accepts a configured multi-person alias only as a
standalone address line. The line must be followed by a street line (matching
`street_number`) and a city line (matching `postal_code`), and must not
directly follow a sender label. Example for the UK:

```yaml
extraction:
  recipient:
    address_rules:
      postal_code: '\b[A-Z]{1,2}\d[A-Z\d]? ?\d[A-Z]{2}\b'
      street_number: '^\d+\s+\w+'
      salutations: [Mr, Mrs, Ms, Mx, Dr]
      sender_labels: [From, Return address]
      name_joiners: ["&", and]
```

## Changing behaviour safely

- Changing the model, prompt, schema or input settings changes the engine
  fingerprint. Cached extractions are then ignored, and documents are
  re-analysed on their next queue run.
- Proposals already stored remain applicable; they record the value they expect.
