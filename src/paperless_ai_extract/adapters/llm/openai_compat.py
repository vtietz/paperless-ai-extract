"""OpenAI-compatible /chat/completions backend.

Works with OpenAI, vLLM, llama.cpp server, LM Studio, LocalAI, LiteLLM and
Ollama's /v1 endpoint. `base_url` includes the API prefix, e.g.
http://host:8000/v1. Images are sent as PNG data URLs.
"""
from __future__ import annotations

import base64

import httpx

from ...config import LLMConfig
from ...domain.errors import LLMError, LLMTimeout
from ...ports import LLMResult
from .base import SYSTEM_PROMPT, strip_fences


class OpenAICompatibleClient:
    def __init__(self, config: LLMConfig, transport: httpx.BaseTransport | None = None):
        self.config = config
        headers = dict(config.headers)
        key = config.resolved_api_key()
        if key:
            headers["Authorization"] = f"Bearer {key}"
        self.http = httpx.Client(
            base_url=config.base_url.rstrip("/"),
            timeout=httpx.Timeout(config.timeout, connect=15),
            headers=headers,
            transport=transport,
        )

    def describe(self) -> dict:
        c = self.config
        return {"provider": "openai", "model": c.model, "options": c.options,
                "structured_output": c.structured_output}

    def generate_json(self, prompt: str, images: list[bytes], schema: dict) -> LLMResult:
        c = self.config
        content: list[dict] = [{"type": "text", "text": prompt}]
        for image in images:
            data = base64.b64encode(image).decode()
            content.append({"type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{data}"}})
        body: dict = {
            **c.options,
            "model": c.model,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                         {"role": "user", "content": content}],
        }
        if c.structured_output == "json_schema":
            body["response_format"] = {"type": "json_schema", "json_schema": {
                "name": "document_metadata", "schema": schema, "strict": False}}
        elif c.structured_output == "json_object":
            body["response_format"] = {"type": "json_object"}
        try:
            response = self.http.post("/chat/completions", json=body)
        except httpx.TimeoutException as exc:
            raise LLMTimeout(f"LLM request timed out after {c.timeout}s") from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"LLM request failed: {exc.__class__.__name__}") from exc
        if response.status_code >= 400:
            raise LLMError(f"LLM HTTP {response.status_code}: {response.text[:300]}")
        try:
            data = response.json()
            message = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMError("LLM returned an unexpected response shape") from exc
        if isinstance(message, list):
            message = "".join(part.get("text", "") for part in message if isinstance(part, dict))
        if not isinstance(message, str):
            raise LLMError("LLM returned no text content")
        return LLMResult(strip_fences(message), dict(data.get("usage") or {}))

    def check(self) -> str:
        try:
            response = self.http.get("/models", timeout=15)
        except httpx.HTTPError as exc:
            raise LLMError(f"cannot reach LLM endpoint: {exc}") from exc
        if response.status_code == 404:
            return "endpoint reachable; /models not implemented, model not verified"
        if response.status_code >= 400:
            raise LLMError(f"LLM /models HTTP {response.status_code}")
        try:
            ids = {m.get("id") for m in response.json().get("data", [])}
        except ValueError as exc:
            raise LLMError("LLM /models returned invalid JSON") from exc
        if ids and self.config.model not in ids:
            raise LLMError(f"model {self.config.model!r} not offered by endpoint")
        return f"openai-compatible ok, model {self.config.model}"
