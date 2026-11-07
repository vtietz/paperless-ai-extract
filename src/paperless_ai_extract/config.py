"""YAML configuration with ${ENV} expansion and file-based secrets.

Relative paths in the file are resolved against the configuration file's
directory, so a config directory can be mounted anywhere.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class ConfigError(Exception):
    pass


_ENV = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def _expand(value: Any) -> Any:
    if isinstance(value, str):
        def replace(match: re.Match) -> str:
            name, default = match.group(1), match.group(2)
            if name in os.environ:
                return os.environ[name]
            if default is not None:
                return default
            raise ConfigError(f"environment variable {name} is not set")
        return _ENV.sub(replace, value)
    if isinstance(value, dict):
        return {key: _expand(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand(item) for item in value]
    return value


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _secret(value: str | None, path: Path | None, what: str) -> str | None:
    if value:
        return value
    if path:
        try:
            return path.read_text().strip()
        except OSError as exc:
            raise ConfigError(f"cannot read {what} file {path}: {exc.strerror}") from None
    return None


class PaperlessConfig(Strict):
    url: str
    token: str | None = None
    token_file: Path | None = None
    timeout: float = 60
    verify_tls: bool = True
    headers: dict[str, str] = Field(default_factory=dict)

    def resolved_token(self) -> str:
        token = _secret(self.token, self.token_file, "Paperless token")
        if not token:
            raise ConfigError("paperless.token or paperless.token_file is required")
        return token


class LLMConfig(Strict):
    provider: Literal["ollama", "openai"] = "ollama"
    base_url: str
    model: str
    api_key: str | None = None
    api_key_file: Path | None = None
    timeout: float = 300
    # Ollama: "options" object. OpenAI-compatible: extra top-level body
    # parameters such as temperature, max_tokens or seed.
    options: dict[str, Any] = Field(default_factory=dict)
    # Ollama "think" flag; null omits it (for models without thinking support).
    think: bool | None = False
    keep_alive: str | None = None
    structured_output: Literal["json_schema", "json_object", "none"] = "json_schema"
    headers: dict[str, str] = Field(default_factory=dict)

    def resolved_api_key(self) -> str | None:
        return _secret(self.api_key, self.api_key_file, "LLM API key")


class InputConfig(Strict):
    mode: Literal["image", "text", "image+text"] = "image"
    pages: int = Field(1, ge=1, le=10)
    max_edge: int = Field(1120, ge=256, le=4096)
    text_chars: int = Field(4000, ge=200)
    # "archive" uses Paperless's archived PDF when present (the OCRed copy),
    # "original" always downloads the uploaded file.
    source: Literal["archive", "original"] = "archive"


class AddressWindowConfig(Strict):
    """Second local OCR reading of a conventional address window (portrait PDF).

    Used only to confirm configured multi-person aliases that the model chose
    but the document text could not corroborate. Defaults fit DIN 5008 letters.
    """
    enabled: bool = False
    languages: str = "deu+eng"
    psm_modes: list[str] = Field(default_factory=lambda: ["6", "11"])
    scale_to: int = 2400
    x: int = 0
    y: int = 240
    width: int = 1100
    height: int = 600
    min_aspect: float = 1.2
    max_aspect: float = 1.8


class AddressRulesConfig(Strict):
    """Locale rules for recognising a postal address block (defaults: German + English)."""
    # A line counts as "city line" when it matches this regular expression.
    postal_code: str = r"\b(?:D[ -]*)?\d{5}\s*[^\W\d_]"
    # A street line ends with a house number.
    street_number: str = r"\d+[a-z]?\s*$"
    salutations: list[str] = Field(default_factory=lambda: [
        "Frau", "Herr", "Herrn", "Familie", "Mr", "Mrs", "Ms", "Mx"])
    sender_labels: list[str] = Field(default_factory=lambda: [
        "Absender", "Auftraggeber", "Sender", "From"])
    name_joiners: list[str] = Field(default_factory=lambda: ["&", "und", "and"])


class RecipientConfig(Strict):
    """A select custom field filled with the addressee (e.g. household member)."""
    enabled: bool = False
    custom_field: str = "Recipient"
    unassigned: str = "Unassigned"
    shared: str | None = None
    shared_keywords: list[str] = Field(default_factory=list)
    # canonical dropdown label -> printed variants that count as that label
    aliases: dict[str, list[str]] = Field(default_factory=dict)
    address_rules: AddressRulesConfig = Field(default_factory=AddressRulesConfig)
    address_window: AddressWindowConfig = Field(default_factory=AddressWindowConfig)


class ArticleConfig(Strict):
    """Optional profile for journal/magazine articles."""
    enabled: bool = False
    kind: str = "article"
    authors_field: str | None = "Authors"
    created_from_year: bool = True
    # Journal, authors and year must occur in the document text.
    require_text_evidence: bool = True


class TagsConfig(Strict):
    """Tags chosen from existing Paperless tags only (controlled vocabulary)."""
    enabled: bool = False
    # Candidate tag names; empty = all tags except inbox and queue tags.
    allowed: list[str] = Field(default_factory=list)
    excluded: list[str] = Field(default_factory=list)
    max_tags: int = Field(3, ge=1, le=10)


class CorrespondentsConfig(Strict):
    """Existing correspondents offered to the model."""
    # shortlist: names (or aliases) found in the document's OCR text, best first;
    # all: every name while there are at most max_listed, else the shortlist; none.
    offer: Literal["shortlist", "all", "none"] = "shortlist"
    max_listed: int = Field(15, ge=1)
    excluded: list[str] = Field(default_factory=list)


class DocumentTypesConfig(Strict):
    """Existing document types offered to the model as its choices."""
    # List the existing types in the prompt; the model picks the best fit and may
    # name a new type unless taxonomy.new_document_types is "never".
    offer_existing: bool = True
    excluded: list[str] = Field(default_factory=list)
    # Larger taxonomies are not listed (prompt size); matching still applies.
    max_listed: int = Field(150, ge=1)


class DocumentDateConfig(Strict):
    """The document's own date (Paperless "created")."""
    enabled: bool = False
    # Paperless already guesses a date at import. "propose" never changes it;
    # "fill" replaces it on the first analysis when the year is printed.
    first_run: Literal["propose", "fill"] = "propose"


class ExtractionConfig(Strict):
    # None = built-in prompt (adapts to the enabled features).
    prompt_file: Path | None = None
    kinds: list[str] = Field(default_factory=lambda: ["document"])
    title_max_length: int = 128
    language: str | None = None   # e.g. "German"; None = language of the document
    recipient: RecipientConfig = Field(default_factory=RecipientConfig)
    articles: ArticleConfig = Field(default_factory=ArticleConfig)
    tags: TagsConfig = Field(default_factory=TagsConfig)
    correspondents: CorrespondentsConfig = Field(default_factory=CorrespondentsConfig)
    document_types: DocumentTypesConfig = Field(default_factory=DocumentTypesConfig)
    document_date: DocumentDateConfig = Field(default_factory=DocumentDateConfig)

    @model_validator(mode="after")
    def _kinds(self):
        if not self.kinds:
            raise ValueError("extraction.kinds must not be empty")
        if self.articles.enabled and self.articles.kind not in self.kinds:
            raise ValueError("extraction.articles.kind must be listed in extraction.kinds")
        return self


NewItemPolicy = Literal["create", "propose", "never"]


class TaxonomyConfig(Strict):
    correspondent_aliases: dict[str, str] = Field(default_factory=dict)
    correspondent_aliases_file: Path | None = None
    # model name -> existing document type, e.g. {"Slide deck": "Presentation"}
    document_type_aliases: dict[str, str] = Field(default_factory=dict)
    # A name with no existing match: create it right away, propose it (created
    # only when the proposal is accepted with the apply tag), or drop it.
    new_correspondents: NewItemPolicy = "propose"
    new_document_types: NewItemPolicy = "propose"
    # Deprecated (0.1/0.2): true -> "create", false -> "propose" (correspondents)
    # or "never" (document types). Ignored when the new_* setting is given.
    create_correspondents: bool | None = None
    create_document_types: bool | None = None
    new_correspondent_requires_text_evidence: bool = True
    # Same difflib cutoff as Paperless's native AI matching; >= 1 disables fuzzy matching.
    fuzzy_threshold: float = 0.8
    # kind -> storage path name; applied only when the document has none.
    storage_paths: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _legacy_create_flags(self):
        given = self.model_fields_set
        if self.create_correspondents is not None and "new_correspondents" not in given:
            self.new_correspondents = "create" if self.create_correspondents else "propose"
        if self.create_document_types is not None and "new_document_types" not in given:
            self.new_document_types = "create" if self.create_document_types else "never"
        return self


FieldName = Literal["title", "correspondent", "document_type", "storage_path",
                    "created", "recipient", "authors", "tags"]


class PolicyConfig(Strict):
    fields: list[FieldName] = Field(default_factory=lambda: [
        "title", "correspondent", "document_type", "storage_path",
        "created", "recipient", "authors", "tags"])
    # first_run: the service has never processed this document before.
    first_run: Literal["fill_empty", "propose"] = "fill_empty"
    rerun: Literal["fill_empty", "propose"] = "propose"
    title_empty_if_filename: bool = True
    notes: Literal["always", "proposals", "never"] = "proposals"
    notes_language: Literal["en", "de"] = "en"


class TagConfig(Strict):
    pending: str = "AI: pending"
    apply: str = "AI: apply"
    proposal: str | None = "AI: proposal"
    review: str | None = "AI: review"
    error: str | None = "AI: error"


class QueueConfig(Strict):
    poll_interval: float = 30
    batch_size: int = 10
    max_attempts: int = 3
    retry_delay: float = 300
    create_missing_tags: bool = True
    tags: TagConfig = Field(default_factory=TagConfig)


class StateConfig(Strict):
    path: Path = Path("/data/state.sqlite3")
    heartbeat_file: Path = Path("/data/heartbeat")


class Config(Strict):
    paperless: PaperlessConfig
    llm: LLMConfig
    input: InputConfig = Field(default_factory=InputConfig)
    extraction: ExtractionConfig = Field(default_factory=ExtractionConfig)
    taxonomy: TaxonomyConfig = Field(default_factory=TaxonomyConfig)
    policy: PolicyConfig = Field(default_factory=PolicyConfig)
    queue: QueueConfig = Field(default_factory=QueueConfig)
    state: StateConfig = Field(default_factory=StateConfig)

    def correspondent_aliases(self) -> dict[str, str]:
        aliases = dict(self.taxonomy.correspondent_aliases)
        path = self.taxonomy.correspondent_aliases_file
        if path:
            import json
            try:
                aliases.update(json.loads(path.read_text()))
            except (OSError, ValueError) as exc:
                raise ConfigError(f"cannot read correspondent aliases {path}: {exc}") from None
        return aliases


def _resolve_paths(model: BaseModel, base: Path) -> None:
    for name, value in model:
        if isinstance(value, Path) and not value.is_absolute():
            setattr(model, name, (base / value).resolve())
        elif isinstance(value, BaseModel):
            _resolve_paths(value, base)


# Convenience variables for container deployments without a config file.
ENV_SHORTCUTS = {
    "PAPERLESS_URL": ("paperless", "url"),
    "PAPERLESS_TOKEN": ("paperless", "token"),
    "PAPERLESS_TOKEN_FILE": ("paperless", "token_file"),
    "LLM_PROVIDER": ("llm", "provider"),
    "LLM_BASE_URL": ("llm", "base_url"),
    "LLM_MODEL": ("llm", "model"),
    "LLM_API_KEY": ("llm", "api_key"),
    "LLM_API_KEY_FILE": ("llm", "api_key_file"),
    "INPUT_MODE": ("input", "mode"),
}
# Any setting: PAE__<SECTION>__<KEY>[__<SUBKEY>...]=<YAML value>,
# e.g. PAE__EXTRACTION__TAGS__ENABLED=true or PAE__LLM__OPTIONS='{num_ctx: 8192}'.
ENV_PREFIX = "PAE__"


def _set(tree: dict, keys: list[str], value) -> None:
    for key in keys[:-1]:
        node = tree.get(key)
        if not isinstance(node, dict):
            node = tree[key] = {}
        tree = node
    tree[keys[-1]] = value


def _apply_env(raw: dict, environ: dict) -> dict:
    for name, keys in ENV_SHORTCUTS.items():
        if environ.get(name):
            _set(raw, list(keys), environ[name])
    for name, value in sorted(environ.items()):
        if name.startswith(ENV_PREFIX) and len(name) > len(ENV_PREFIX):
            keys = [part.lower() for part in name[len(ENV_PREFIX):].split("__") if part]
            try:
                parsed = yaml.safe_load(value)
            except yaml.YAMLError:
                parsed = value
            # Only explicit [..] or {..} become collections; "AI: pending" stays a string.
            if isinstance(parsed, (dict, list)) and not value.lstrip().startswith(("{", "[")):
                parsed = value
            if value.lstrip().startswith(("{", "[")) and isinstance(parsed, str):
                raise ConfigError(f"invalid YAML value in {name}")
            _set(raw, keys, parsed)
    return raw


def load_config(path: str | Path | None, environ: dict | None = None) -> Config:
    """Load YAML (optional) and apply environment overrides; env wins."""
    environ = dict(os.environ if environ is None else environ)
    raw: dict = {}
    base = Path.cwd()
    if path is not None:
        path = Path(path)
        if path.exists():
            try:
                raw = yaml.safe_load(path.read_text()) or {}
            except OSError as exc:
                raise ConfigError(f"cannot read config {path}: {exc.strerror}") from None
            except yaml.YAMLError as exc:
                raise ConfigError(f"invalid YAML in {path}: {exc}") from None
            base = path.parent.resolve()
        elif not any(environ.get(n) for n in ENV_SHORTCUTS) and not any(
                n.startswith(ENV_PREFIX) for n in environ):
            raise ConfigError(f"config {path} not found and no environment configuration set")
    if not isinstance(raw, dict):
        raise ConfigError("config root must be a mapping")
    try:
        config = Config.model_validate(_apply_env(_expand(raw), environ))
    except ValidationError as exc:
        raise ConfigError(f"invalid configuration:\n{exc}") from None
    _resolve_paths(config, base)
    return config
