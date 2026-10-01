import json
from types import SimpleNamespace

import httpx
import pytest
from openrouter import OpenRouter
from openrouter.utils import BackoffStrategy, RetryConfig

from llm import OpenRouterClient, OpenRouterError, OpenRouterModel, embed
from llm.openrouter import default_sdk

MESSAGES = [{"role": "user", "content": "Hi"}]


@pytest.fixture(autouse=True)
def fresh_default_sdk():
    default_sdk.cache_clear()
    yield
    default_sdk.cache_clear()


def client_for(handler) -> OpenRouterClient:
    # No retries, so a transport error fails at once (the SDK default retries for up to an hour).
    sdk = OpenRouter(api_key="test", client=httpx.Client(transport=httpx.MockTransport(handler)),
                     retry_config=RetryConfig("none", BackoffStrategy(0, 0, 1, 0), False))
    return OpenRouterClient(model=OpenRouterModel.GPT_4O, sdk=sdk)


def test_chat_returns_the_answer():
    def handler(request):
        assert request.url.path.endswith("/chat/completions")
        assert request.headers["authorization"] == "Bearer test"
        body = json.loads(request.content)
        assert body["model"] == "openai/gpt-4o"
        assert body["messages"] == MESSAGES
        return httpx.Response(200, json={
            "id": "gen-1", "object": "chat.completion", "created": 1, "model": "openai/gpt-4o",
            "system_fingerprint": None,
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": "Hello"}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4},
        })

    assert client_for(handler).chat(MESSAGES) == "Hello"


def test_stream_yields_content_pieces():
    def chunk(content):
        return {"id": "gen-1", "object": "chat.completion.chunk", "created": 1, "model": "openai/gpt-4o",
                "choices": [{"index": 0, "finish_reason": None, "delta": {"content": content}}]}

    def handler(request):
        assert json.loads(request.content)["stream"] is True
        sse = "".join(f"data: {json.dumps(chunk(c))}\n\n" for c in ["Hel", "lo"]) + "data: [DONE]\n\n"
        return httpx.Response(200, content=sse.encode(), headers={"content-type": "text/event-stream"})

    assert list(client_for(handler).stream(MESSAGES)) == ["Hel", "lo"]


def test_missing_key_fails_early(monkeypatch):
    monkeypatch.delenv("OR_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OR_KEY"):
        OpenRouterClient()


def test_default_model_is_haiku(monkeypatch):
    monkeypatch.delenv("LLM_OPENROUTER_MODEL", raising=False)
    assert OpenRouterClient(sdk=OpenRouter(api_key="test")).model is OpenRouterModel.HAIKU


def test_model_from_env(monkeypatch):
    monkeypatch.setenv("LLM_OPENROUTER_MODEL", "anthropic/claude-sonnet-5.5")
    assert OpenRouterClient(sdk=OpenRouter(api_key="test")).model is OpenRouterModel.SONNET


def test_unknown_model_in_env_fails(monkeypatch):
    monkeypatch.setenv("LLM_OPENROUTER_MODEL", "openai/gpt-3")
    with pytest.raises(RuntimeError, match="LLM_OPENROUTER_MODEL"):
        OpenRouterClient(sdk=OpenRouter(api_key="test"))


def test_haiku_sends_its_openrouter_id():
    def handler(request):
        assert json.loads(request.content)["model"] == "anthropic/claude-haiku-4.5"
        return httpx.Response(200, json={
            "id": "gen-1", "object": "chat.completion", "created": 1,
            "model": "anthropic/claude-haiku-4.5", "system_fingerprint": None,
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": "Hi"}}],
        })

    sdk = OpenRouter(api_key="test", client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert OpenRouterClient(model=OpenRouterModel.HAIKU, sdk=sdk).chat(MESSAGES) == "Hi"


def test_chat_span_carries_model_tokens_and_cost(spans):
    def handler(request):
        return httpx.Response(200, json={
            "id": "gen-1", "object": "chat.completion", "created": 1, "model": "openai/gpt-4o-2024-08-06",
            "system_fingerprint": None,
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": "Hello"}}],
            "usage": {"prompt_tokens": 30, "completion_tokens": 10, "total_tokens": 40, "cost": 0.00125,
                      "prompt_tokens_details": {"cached_tokens": 20},
                      "cost_details": {"upstream_inference_prompt_cost": 0.00025,
                                       "upstream_inference_completions_cost": 0.001}},
        })

    client_for(handler).chat(MESSAGES)
    [span] = [s for s in spans.get_finished_spans() if s.name == "openrouter.chat"]
    a = span.attributes
    assert a["openinference.span.kind"] == "LLM"
    assert a["llm.model_name"] == "openai/gpt-4o-2024-08-06"  # the model OpenRouter used
    assert a["llm.provider"] == "openai"
    assert (a["llm.token_count.prompt"], a["llm.token_count.completion"], a["llm.token_count.total"]) == (30, 10, 40)
    assert a["llm.token_count.prompt_details.cache_read"] == 20
    assert a["llm.cost.total"] == 0.00125
    assert (a["llm.cost.prompt"], a["llm.cost.completion"]) == (0.00025, 0.001)
    assert a["output.value"] == "Hello"


def test_stream_span_gets_usage_from_last_chunk(spans):
    def chunk(content, usage=None):
        body = {"id": "gen-1", "object": "chat.completion.chunk", "created": 1, "model": "openai/gpt-4o",
                "choices": [{"index": 0, "finish_reason": None, "delta": {"content": content}}] if content else []}
        if usage:
            body["usage"] = usage
        return body

    def handler(request):
        events = [chunk("Hel"), chunk("lo"),
                  chunk(None, {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5, "cost": 0.0001})]
        sse = "".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"
        return httpx.Response(200, content=sse.encode(), headers={"content-type": "text/event-stream"})

    assert "".join(client_for(handler).stream(MESSAGES)) == "Hello"
    [span] = [s for s in spans.get_finished_spans() if s.name == "openrouter.chat"]
    assert span.attributes["llm.cost.total"] == 0.0001
    assert span.attributes["output.value"] == "Hello"


def test_http_error_is_a_service_fault():
    from observability import ServiceFault

    def handler(request):
        return httpx.Response(401, json={"error": {"code": 401, "message": "No auth credentials found"}})

    with pytest.raises(ServiceFault):
        client_for(handler).chat(MESSAGES)


def test_default_sdk_has_bounded_timeout_and_retries(monkeypatch):
    monkeypatch.setenv("OR_KEY", "test")
    monkeypatch.delenv("LLM_TIMEOUT_S", raising=False)
    config = default_sdk().sdk_configuration
    assert config.timeout_ms == 120_000
    backoff = config.retry_config.backoff
    assert config.retry_config.strategy == "backoff"
    assert (backoff.initial_interval, backoff.max_interval, backoff.max_elapsed_time) == (500, 4000, 20000)


def test_timeout_from_env(monkeypatch):
    monkeypatch.setenv("OR_KEY", "test")
    monkeypatch.setenv("LLM_TIMEOUT_S", "7.5")
    assert default_sdk().sdk_configuration.timeout_ms == 7500


def test_chat_and_embed_share_one_cached_sdk(monkeypatch):
    monkeypatch.setenv("OR_KEY", "test")
    sdk = default_sdk()
    assert OpenRouterClient().sdk is sdk
    seen = []
    monkeypatch.setattr(sdk.embeddings, "generate", lambda **kw: seen.append(kw) or SimpleNamespace(
        data=[SimpleNamespace(embedding=[0.1])], usage=None))
    embed("a")
    embed("b")
    assert [kw["input"] for kw in seen] == ["a", "b"]
    assert default_sdk() is sdk


def test_transport_error_is_an_openrouter_error():
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(OpenRouterError, match="refused"):
        client_for(handler).chat(MESSAGES)
    with pytest.raises(OpenRouterError, match="refused"):
        list(client_for(handler).stream(MESSAGES))


def test_empty_choices_is_an_openrouter_error():
    def handler(request):
        return httpx.Response(200, json={
            "id": "gen-1", "object": "chat.completion", "created": 1, "model": "openai/gpt-4o",
            "system_fingerprint": None, "choices": [],
        })

    with pytest.raises(OpenRouterError, match="no choices"):
        client_for(handler).chat(MESSAGES)
