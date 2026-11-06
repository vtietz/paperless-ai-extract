import base64
import json

import httpx
import pytest

from paperless_ai_extract.adapters.llm import create_llm_client
from paperless_ai_extract.adapters.llm.ollama import OllamaClient
from paperless_ai_extract.adapters.llm.openai_compat import OpenAICompatibleClient
from paperless_ai_extract.config import LLMConfig
from paperless_ai_extract.domain.errors import LLMError, LLMTimeout

SCHEMA = {"type": "object", "properties": {"title": {"type": "string"}}}


def recorder(response):
    seen = {}

    def handler(request: httpx.Request):
        seen["request"] = request
        seen["body"] = json.loads(request.content) if request.content else None
        return response(request) if callable(response) else response
    return seen, httpx.MockTransport(handler)


def test_ollama_request_shape_and_metrics():
    seen, transport = recorder(httpx.Response(200, json={
        "message": {"content": '{"title": "x"}'}, "prompt_eval_count": 1700, "eval_count": 40}))
    cfg = LLMConfig(base_url="http://o:11434", model="m", options={"num_ctx": 4096}, keep_alive="10m")
    result = OllamaClient(cfg, transport).generate_json("P", [b"img"], SCHEMA)
    body = seen["body"]
    assert seen["request"].url.path == "/api/chat"
    assert body["format"] == SCHEMA and body["think"] is False and body["stream"] is False
    assert body["options"] == {"num_ctx": 4096} and body["keep_alive"] == "10m"
    assert body["messages"][0]["role"] == "system"
    assert body["messages"][1]["images"] == [base64.b64encode(b"img").decode()]
    assert result.content == '{"title": "x"}' and result.metrics["prompt_eval_count"] == 1700


def test_ollama_think_null_is_omitted_and_json_mode():
    seen, transport = recorder(httpx.Response(200, json={"message": {"content": "{}"}}))
    cfg = LLMConfig(base_url="http://o", model="m", think=None, structured_output="json_object")
    OllamaClient(cfg, transport).generate_json("P", [], SCHEMA)
    assert "think" not in seen["body"] and seen["body"]["format"] == "json"
    assert "images" not in seen["body"]["messages"][1]


def test_ollama_errors_are_mapped():
    _, transport = recorder(httpx.Response(500, text="boom"))
    with pytest.raises(LLMError, match="HTTP 500"):
        OllamaClient(LLMConfig(base_url="http://o", model="m"), transport).generate_json("P", [], SCHEMA)

    def timeout(request):
        raise httpx.ReadTimeout("slow", request=request)
    with pytest.raises(LLMTimeout):
        OllamaClient(LLMConfig(base_url="http://o", model="m"),
                     httpx.MockTransport(timeout)).generate_json("P", [], SCHEMA)


def test_ollama_check_model_installed():
    _, transport = recorder(httpx.Response(200, json={"models": [{"name": "m:latest"}]}))
    assert "installed" in OllamaClient(LLMConfig(base_url="http://o", model="m"), transport).check()
    with pytest.raises(LLMError):
        OllamaClient(LLMConfig(base_url="http://o", model="other"), transport).check()


def test_openai_request_shape():
    seen, transport = recorder(httpx.Response(200, json={
        "choices": [{"message": {"content": '```json\n{"title": "x"}\n```'}}],
        "usage": {"prompt_tokens": 5}}))
    cfg = LLMConfig(provider="openai", base_url="http://v/v1", model="qwen-vl",
                    api_key="k", options={"temperature": 0.1, "max_tokens": 768})
    result = OpenAICompatibleClient(cfg, transport).generate_json("P", [b"img"], SCHEMA)
    body = seen["body"]
    assert seen["request"].url.path == "/v1/chat/completions"
    assert seen["request"].headers["authorization"] == "Bearer k"
    assert body["temperature"] == 0.1 and body["max_tokens"] == 768 and body["model"] == "qwen-vl"
    parts = body["messages"][1]["content"]
    assert parts[0] == {"type": "text", "text": "P"}
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert body["response_format"]["json_schema"]["schema"] == SCHEMA
    assert result.content == '{"title": "x"}'


def test_openai_without_key_sends_no_auth_and_bad_shape_fails():
    seen, transport = recorder(httpx.Response(200, json={"choices": []}))
    client = OpenAICompatibleClient(LLMConfig(provider="openai", base_url="http://v/v1", model="m"),
                                    transport)
    with pytest.raises(LLMError, match="unexpected"):
        client.generate_json("P", [], SCHEMA)
    assert "authorization" not in seen["request"].headers


def test_factory():
    assert isinstance(create_llm_client(LLMConfig(base_url="http://o", model="m")), OllamaClient)
    assert isinstance(create_llm_client(LLMConfig(provider="openai", base_url="http://o", model="m")),
                      OpenAICompatibleClient)
