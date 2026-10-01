import json
from types import SimpleNamespace

import httpx
import pytest
from openrouter import OpenRouter
from openrouter.utils import BackoffStrategy, RetryConfig

from llm import DEFAULT_EMBED_MODEL, OpenRouterError, embed


class FakeEmbeddings:
    def generate(self, model, input, encoding_format, timeout_ms):
        assert model == "m" and input == "long text" and encoding_format == "float"
        assert timeout_ms == 30_000
        return SimpleNamespace(data=[SimpleNamespace(embedding=[0.1, 0.2])],
                               usage=SimpleNamespace(prompt_tokens=4))


def sdk_for(handler) -> OpenRouter:
    # No retries, so a transport error fails at once (the SDK default retries for up to an hour).
    return OpenRouter(api_key="test", client=httpx.Client(transport=httpx.MockTransport(handler)),
                      retry_config=RetryConfig("none", BackoffStrategy(0, 0, 1, 0), False))


def test_embed_flags_truncation():
    e = embed("long text", model="m", max_tokens=4, sdk=SimpleNamespace(embeddings=FakeEmbeddings()))
    assert e.vector == [0.1, 0.2]
    assert e.token_count == 4
    assert e.truncated


def test_default_model(monkeypatch):
    monkeypatch.delenv("LLM_EMBED_MODEL", raising=False)

    def handler(request):
        assert json.loads(request.content)["model"] == DEFAULT_EMBED_MODEL == "openai/text-embedding-3-small"
        return httpx.Response(200, json={"object": "list", "model": DEFAULT_EMBED_MODEL,
                                         "data": [{"object": "embedding", "index": 0, "embedding": [0.5]}]})

    assert embed("Hi", sdk=sdk_for(handler)).vector == [0.5]


def test_empty_data_is_an_openrouter_error():
    def handler(request):
        return httpx.Response(200, json={"object": "list", "model": "m", "data": []})

    with pytest.raises(OpenRouterError, match="no embedding"):
        embed("Hi", model="m", sdk=sdk_for(handler))


def test_http_error_is_an_openrouter_error():
    def handler(request):
        return httpx.Response(401, json={"error": {"code": 401, "message": "No auth credentials found"}})

    with pytest.raises(OpenRouterError):
        embed("Hi", model="m", sdk=sdk_for(handler))


def test_transport_error_is_an_openrouter_error():
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(OpenRouterError, match="refused"):
        embed("Hi", model="m", sdk=sdk_for(handler))
