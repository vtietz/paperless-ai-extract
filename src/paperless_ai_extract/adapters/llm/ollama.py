"""Ollama native /api/chat backend (structured output via `format`)."""
from __future__ import annotations

import base64

import httpx

from ...config import LLMConfig
from ...domain.errors import LLMError, LLMTimeout
from ...ports import LLMResult
from .base import SYSTEM_PROMPT, strip_fences


class OllamaClient:
    def __init__(self, config: LLMConfig, transport: httpx.BaseTransport | None = None):
        self.config = config
        self.http = httpx.Client(
            base_url=config.base_url.rstrip("/"),
            timeout=httpx.Timeout(config.timeout, connect=15),
            headers=config.headers,
            transport=transport,
        )

    def describe(self) -> dict:
        c = self.config
        return {"provider": "ollama", "model": c.model, "options": c.options,
                "think": c.think, "structured_output": c.structured_output}

    def generate_json(self, prompt: str, images: list[bytes], schema: dict) -> LLMResult:
        c = self.config
        user = {"role": "user", "content": prompt}
        if images:
            user["images"] = [base64.b64encode(image).decode() for image in images]
        body: dict = {
            "model": c.model,
            "stream": False,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}, user],
            "options": c.options,
        }
        if c.structured_output == "json_schema":
            body["format"] = schema
        elif c.structured_output == "json_object":
            body["format"] = "json"
        if c.think is not None:
            body["think"] = c.think
        if c.keep_alive is not None:
            body["keep_alive"] = c.keep_alive
        try:
            response = self.http.post("/api/chat", json=body)
        except httpx.TimeoutException as exc:
            raise LLMTimeout(f"Ollama request timed out after {c.timeout}s") from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"Ollama request failed: {exc.__class__.__name__}") from exc
        if response.status_code >= 400:
            raise LLMError(f"Ollama HTTP {response.status_code}: {response.text[:300]}")
        try:
            data = response.json()
            content = data["message"]["content"]
        except (ValueError, KeyError, TypeError) as exc:
            raise LLMError("Ollama returned an unexpected response shape") from exc
        metrics = {key: data.get(key) for key in
                   ("prompt_eval_count", "eval_count", "total_duration") if key in data}
        return LLMResult(strip_fences(content), metrics)

    def check(self) -> str:
        try:
            response = self.http.get("/api/tags", timeout=15)
            response.raise_for_status()
            names = {m.get("name") for m in response.json().get("models", [])}
        except (httpx.HTTPError, ValueError) as exc:
            raise LLMError(f"cannot list Ollama models: {exc}") from exc
        model = self.config.model
        if model not in names and f"{model}:latest" not in names:
            raise LLMError(f"model {model!r} is not installed in Ollama")
        return f"ollama ok, model {model} installed"
