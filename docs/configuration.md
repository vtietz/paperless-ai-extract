# Configuration reference

A single YAML file (default `/config/config.yaml`). Relative paths are resolved
against the file's directory. Unknown keys are rejected. `${NAME}` and
`${NAME:-default}` are expanded from the environment.

```yaml
paperless:
  url: http://paperless:8000          # base URL as seen from the service
  token: ${PAPERLESS_TOKEN}           # or token_file: /run/secrets/paperless_token
  timeout: 60
  verify_tls: true
  headers: {}                         # e.g. {Host: paperless.example.org} if ALLOWED_HOSTS requires it

llm:
  provider: ollama                    # ollama | openai
  base_url: http://ollama:11434       # openai: include /v1
  model: qwen3.5:4b
  api_key: ${LLM_API_KEY:-}           # or api_key_file
  timeout: 300
  options: {num_ctx: 4096, temperature: 0.1}   # passed through to the backend
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
  prompt_file: prompt.txt             # see placeholders below
  kinds: [document]                   # e.g. [household, article]
  title_max_length: 128
  recipient:                          # optional select custom field
    enabled: false
    custom_field: Recipient
    unassigned: Unassigned            # must exist in the dropdown
    shared: null                      # optional option for household-wide documents
    shared_keywords: []               # words that must appear in the addressee quote
    aliases: {}                       # "Canonical label": ["printed variant", ...]
    address_window:
      enabled: false                  # second OCR reading for joint aliases
      languages: deu+eng              # installed Tesseract languages (image build arg)
      psm_modes: ["6", "11"]
      scale_to: 2400
      x: 0
      y: 240
      width: 1100
      height: 600                     # window in pixels at scale_to
  articles:
    enabled: false
    kind: article                     # must be listed in kinds
    authors_field: Authors            # long-text custom field
    created_from_year: true
    require_text_evidence: true       # journal, authors and year must be in the OCR text

taxonomy:
  correspondent_aliases: {}           # "printed name": "canonical correspondent"
  correspondent_aliases_file: null    # JSON object with the same shape
  create_correspondents: true         # created unowned (shared), like Paperless's AI workflow
  create_document_types: true
  new_correspondent_requires_text_evidence: true
  fuzzy_threshold: 0.8                # difflib cutoff; >= 1 disables fuzzy matching
  storage_paths: {}                   # kind: "Storage path name" (only when empty)

policy:
  fields: [title, correspondent, document_type, storage_path, created, recipient, authors]
  first_run: fill_empty               # fill_empty | propose
  rerun: propose                      # fill_empty | propose
  title_empty_if_filename: true
  notes: proposals                    # always | proposals | never

queue:
  poll_interval: 30
  batch_size: 10
  max_attempts: 3
  retry_delay: 300                    # seconds × attempt number
  create_missing_tags: false
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

## Prompt placeholders

The prompt file uses Python `string.Template` syntax:

| Placeholder | Value |
|---|---|
| `${source_description}` | for example "attached first-page image", "OCR text" |
| `${input_hint}` | layout hint for image modes, empty for text |
| `${kinds}` | JSON list of `extraction.kinds` |
| `${recipient_options}` | JSON list of dropdown labels |
| `${recipient_aliases}` | `Alias: printed => canonical` lines |

The model returns JSON with the fields `kind`, `authors`, `publication_year`,
`title`, `correspondents` (0–1), `document_types` (0–1), `addressee_text` and
`recipient`. Fields are present only when the corresponding feature is enabled.
The prompt should explain how to fill each one.

## Changing behaviour safely

- Changing the model, prompt, schema or input settings changes the engine
  fingerprint. Cached extractions are then ignored, and documents are
  re-analysed on their next queue run.
- Proposals already stored remain applicable; they record the value they expect.
