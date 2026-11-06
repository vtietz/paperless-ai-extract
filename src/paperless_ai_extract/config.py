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
    but the document text could not corroborate.
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


class RecipientConfig(Strict):
    enabled: bool = False
    custom_field: str = "Recipient"
    unassigned: str = "Unassigned"
    shared: str | None = None
    shared_keywords: list[str] = Field(default_factory=list)
    # canonical dropdown label -> printed variants that count as that label
    aliases: dict[str, list[str]] = Field(default_factory=dict)
    address_window: AddressWindowConfig = Field(default_factory=AddressWindowConfig)


class ArticleConfig(Strict):
    enabled: bool = False
    kind: str = "article"
    authors_field: str | None = "Authors"
    created_from_year: bool = True
    # Journal, authors and year must occur in the document text.
    require_text_evidence: bool = True


class ExtractionConfig(Strict):
    prompt_file: Path
    kinds: list[str] = Field(default_factory=lambda: ["document"])
    title_max_length: int = 128
    recipient: RecipientConfig = Field(default_factory=RecipientConfig)
    articles: ArticleConfig = Field(default_factory=ArticleConfig)

    @model_validator(mode="after")
    def _kinds(self):
        if not self.kinds:
            raise ValueError("extraction.kinds must not be empty")
        if self.articles.enabled and self.articles.kind not in self.kinds:
            raise ValueError("extraction.articles.kind must be listed in extraction.kinds")
        return self


class TaxonomyConfig(Strict):
    correspondent_aliases: dict[str, str] = Field(default_factory=dict)
    correspondent_aliases_file: Path | None = None
    create_correspondents: bool = True
    create_document_types: bool = True
    new_correspondent_requires_text_evidence: bool = True
    # Same difflib cutoff as Paperless's native AI matching; >= 1 disables fuzzy matching.
    fuzzy_threshold: float = 0.8
    # kind -> storage path name; applied only when the document has none.
    storage_paths: dict[str, str] = Field(default_factory=dict)


FieldName = Literal["title", "correspondent", "document_type", "storage_path",
                    "created", "recipient", "authors"]


class PolicyConfig(Strict):
    fields: list[FieldName] = Field(default_factory=lambda: [
        "title", "correspondent", "document_type", "storage_path",
        "created", "recipient", "authors"])
    # first_run: the service has never processed this document before.
    first_run: Literal["fill_empty", "propose"] = "fill_empty"
    rerun: Literal["fill_empty", "propose"] = "propose"
    title_empty_if_filename: bool = True
    notes: Literal["always", "proposals", "never"] = "proposals"


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
    create_missing_tags: bool = False
    tags: TagConfig = Field(default_factory=TagConfig)


class StateConfig(Strict):
    path: Path = Path("/data/state.sqlite3")
    heartbeat_file: Path = Path("/data/heartbeat")


class Config(Strict):
    paperless: PaperlessConfig
    llm: LLMConfig
    input: InputConfig = Field(default_factory=InputConfig)
    extraction: ExtractionConfig
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


def load_config(path: str | Path) -> Config:
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except OSError as exc:
        raise ConfigError(f"cannot read config {path}: {exc.strerror}") from None
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {path}: {exc}") from None
    try:
        config = Config.model_validate(_expand(raw))
    except ValidationError as exc:
        raise ConfigError(f"invalid config {path}:\n{exc}") from None
    _resolve_paths(config, path.parent.resolve())
    return config
