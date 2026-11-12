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
  correspondents:                     # existing correspondents offered to the model
    offer: shortlist                  # shortlist (names found in the OCR text) | all | none
    max_listed: 15                    # shortlist size; "all" falls back to the shortlist above this
    excluded: []
  document_types:                     # existing types offered to the model
    offer_existing: true              # list them in the prompt; the model picks the best fit
    excluded: []                      # type names never offered
    max_listed: 150                   # more types than this: not listed (prompt size)
  document_date:
    enabled: false
    first_run: propose                # propose | fill (fill only when the date is printed)
  recipient:                          # optional select custom field for the addressee
    enabled: false
    auto_fill_unassigned: false        # verified recipient fills empty/Unassigned even on reruns
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
  new_correspondents: create          # no existing match: create (if in OCR text, see below) | propose (created on apply) | never
  new_document_types: propose         # never: the model may only choose listed types (schema enum)
  new_correspondent_requires_text_evidence: true
  fuzzy_threshold: 0.8                # difflib cutoff; >= 1 disables fuzzy matching

policy:
  fields: [title, correspondent, document_type, created, recipient, authors, tags]
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
| `${correspondent_options}` | JSON list of existing correspondents offered for this document |
| `${recipient_options}` | JSON list of dropdown labels |
| `${recipient_aliases}` | `Alias: printed => canonical` lines |

The model returns JSON with the fields `kind`, `authors`, `publication_year`,
`title`, `correspondents` (0–1), `document_types` (0–1), `tags`,
`document_date`, `addressee_text` and `recipient`. Each field is present only
when its feature is enabled. Tags are an enum of the selectable tags; unknown
tags are dropped. Document types are an enum of the listed types only when
`new_document_types` is `never`; otherwise the model may name a new type,
which is matched (alias, exact, fuzzy) first.

New correspondents and types are created unowned (shared). With `propose` they
appear in the note with "(new)" and are created when the proposal is accepted
with the apply tag. The settings `create_correspondents` / `create_document_types`
of 0.1/0.2 still work: `true` means `create`; `false` means `propose` for
correspondents and `never` for document types.

Since 0.5 new correspondents default to `create`: a new sender is created and
set automatically when its name occurs in the OCR text
(`new_correspondent_requires_text_evidence: true`); names that are not found stay
proposals. The text check does not catch OCR misspellings ("Serwice"), so review
new correspondents from time to time and map variants with
`correspondent_aliases`. For a first bulk import into an empty correspondent
list, `propose` is the more cautious choice.

## Ownership and sharing

Paperless checks access to documents and their metadata objects separately.
Global model permissions are required, but do not make another user's privately
owned correspondents visible to the service account. A shared document may
therefore reference a correspondent the service cannot retrieve.

If an organisation is clearly recognised but proposed as "(new)", check whether
an existing correspondent is private. The UI may display "Private" instead of
its name, and the service account's API request for that object's ID may return
404. The extractor cannot match entries hidden from its API account; accepting
such a proposal can create a duplicate.

If the correct name appears after a page reload, the browser's cached metadata
list may instead be stale after an API-created correspondent. Reload before
changing permissions; a "Private" label alone does not prove an access denial.

For a household with shared organisation names, use ownerless correspondents.
In Paperless's Correspondents management screen, edit the entry's permissions
and clear its owner. Ownerless entries are accessible to accounts with the
relevant global permissions; they are not restricted to one household group.
Alternatively, retain the owner and explicitly grant view access to the service
account and view/change access to the household group. Do the same for other
metadata objects the service needs to read. Making a correspondent shared does
not change the permissions of documents associated with it.

These changes persist and are picked up on subsequent analyses. Reanalyse
before accepting an old proposal that calls a now-visible entry "new".
Existing entries can be shared in bulk; future entries created manually still
use the creating user's defaults under **Settings → Permissions**. Check these
defaults for each account: they also affect other newly created objects and do
not retroactively change existing entries. The extractor already creates new
correspondents and document types with `owner: null`.

Documents imported through the consume folder normally have no owner unless a
workflow or other import setting assigns one. This does not determine ownership
of separately created correspondents. The optional `Recipient` custom field is
filing metadata, not a Paperless owner or access-control setting.

## Storage paths

The service does not set storage paths (removed in 0.4.0). Paperless already
covers this better:

- One scheme for everything: `PAPERLESS_FILENAME_FORMAT`, for example
  `{{ custom_fields | get_cf_value("Recipient", "Unassigned") }}/{{ correspondent }}/{{ created }} - {{ title }}`.
  Documents without a storage path use it.
- Exceptions as a Paperless workflow: triggers *Document Added* and *Document
  Updated*, filter *has document type* (e.g. "Article"), action *Assignment* →
  storage path. It runs when this service sets the type through the API and
  when you change the type by hand.

A configuration that still contains `taxonomy.storage_paths` is rejected with
a message pointing here.

## Correspondent shortlist

Listing every correspondent would cost tokens on every request and grows with
your archive. By default the service lists only names that probably occur in
the document: before the model call it searches Paperless's OCR text for each
correspondent name and the configured aliases (whole name, or the significant
words of the name, tolerant of OCR errors; legal forms like GmbH are ignored)
and lists the best `max_listed`. The model uses an exact listed name when the
sender is among them, otherwise writes the name as printed, which is then
matched as before. The shortlist is part of the cache key.

## Locale rules for addresses

`addressee_text` should contain only the printed recipient/holder names, without
street, postcode or city. The complete quote must be supported by OCR; returning
a whole postal address can reject a correct recipient because the address text
differs. Custom prompts should explicitly request names only. Evidence checks
remain strict; a model prediction alone does not confirm a recipient.

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

### Automatic recipient fill

`extraction.recipient.auto_fill_unassigned` defaults to `false`. Enable it to
automatically fill a verified recipient when the current value is empty or the
configured Unassigned option, including re-analysis with `rerun: propose`.
Selected people and Shared remain protected; unverified readings still require
review. This exception applies only to the recipient and respects `policy.fields`.
Other metadata continues to follow the normal first-run/rerun policy. It does not
automatically queue existing documents.

### Recipient second image pass

`extraction.recipient.second_image_pass` defaults to `false`. Enable it to retry
recipient confirmation with a fresh image-only request when text evidence and
the existing joint-address OCR fallback fail. No household options, OCR or first
answer are included. A clear full name must match the first extraction's canonical
recipient exactly after case/punctuation/spacing normalization. The first page
is rendered at at least 1600 pixels. Shared/Unassigned choices and text-only mode
are excluded. Failures or ambiguity preserve review; manual selections and rerun
proposal policy remain unchanged. This uses the same configured model and may
add one inference per affected analysis, including cached first extractions.

### Blind names

`extraction.blind_names: true` removes recipient labels/aliases and correspondent
options from generated prompts, and removes the recipient schema enum. Custom
prompts must also remove literal name lists and ask for verbatim recipient names
in `addressee_text`. Matching is deterministic against canonical names and explicit
aliases, ignoring word order, punctuation, case and common honorifics. Exactly one
label must match; surname-only and ambiguous matches fail closed. The special
Shared label is not guessed. Full names matched from the image bypass OCR.

With recipient `second_image_pass: true`, unmatched recipients can receive a
fresh first-page name reading, then the same unique matching. New correspondent
names without text evidence also receive a blind sender reading: its name must
agree after normalization/configured aliases to bypass the text requirement.
Existing-name matching, manual values, rerun proposals and article publication
checks are preserved. Blind mode should use image input. Text-only mode does not
run image fallbacks. Cache fingerprints include matching rules/dropdown labels.

Additional full given names are accepted between a canonical given-name prefix
and its surname, without configuring combinations. Each joint person must match
one-to-one; multiple matching recipient options fail closed. Additional initials,
digits, changed surnames and names prepended before the canonical first name are
not accepted by this extension. Explicit alias and existing exact matching remain
available. Matching revision 2 invalidates old extraction caches.
