"""LLM adapters. Add a provider by implementing ports.LLMClient and registering it here."""
from ...config import LLMConfig
from ...ports import LLMClient


def create_llm_client(config: LLMConfig) -> LLMClient:
    if config.provider == "ollama":
        from .ollama import OllamaClient
        return OllamaClient(config)
    if config.provider == "openai":
        from .openai_compat import OpenAICompatibleClient
        return OpenAICompatibleClient(config)
    raise ValueError(f"unsupported LLM provider {config.provider!r}")
