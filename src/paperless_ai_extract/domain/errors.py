"""Error taxonomy shared by all layers.

Retryable errors leave the document queued; permanent ones mark it failed.
"""


class ExtractError(Exception):
    retryable = True


class ExtractionError(ExtractError):
    """The model answer violated the schema (retryable: sampling varies)."""


class LLMError(ExtractError):
    """The LLM backend failed or returned an unusable response."""


class LLMTimeout(LLMError):
    pass


class StoreError(ExtractError):
    """The document store (Paperless API) failed."""


class UnsupportedInput(ExtractError):
    """The document cannot be analysed in the configured input mode."""
    retryable = False
