"""Chat and streaming through OpenRouter, using its official SDK (`openrouter`).

OpenRouter fronts many providers behind one key. The models this repo uses are listed in
`OpenRouterModel`; Haiku is the default. The key comes from OR_KEY, never the repo.

Each call is an OpenInference LLM span (sent to Phoenix through observability/) carrying the model
OpenRouter actually used, the token counts and the cost OpenRouter billed (`llm.cost.*`), so
Phoenix shows cost per call, per trace and per experiment. It is also the `llm.chat` operation
(count, latency, outcome). An error from OpenRouter is a modelled failure (`OpenRouterError`, a
`ServiceFault`).
"""

import json
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from enum import StrEnum
from functools import cache

import httpx
from common.log import get_logger
from observability import ServiceFault, operation, tracer
from openinference.semconv.trace import (
    OpenInferenceLLMProviderValues,
    OpenInferenceMimeTypeValues,
    OpenInferenceSpanKindValues,
    SpanAttributes,
)
from openrouter import OpenRouter
from openrouter import errors as sdk_errors
from openrouter.utils import BackoffStrategy, RetryConfig

log = get_logger("llm.openrouter")
_tracer = tracer("llm.openrouter")
_PROVIDERS = {p.value for p in OpenInferenceLLMProviderValues}


class OpenRouterModel(StrEnum):
    """OpenRouter model IDs (`<vendor>/<model>`, see https://openrouter.ai/models)."""

    HAIKU = "anthropic/claude-haiku-4.5"
    SONNET = "anthropic/claude-sonnet-5.5"
    OPUS = "anthropic/claude-opus-5.5"
    GPT_4O = "openai/gpt-4o"


DEFAULT_MODEL = OpenRouterModel.HAIKU


class OpenRouterError(ServiceFault):
    """OpenRouter answered with an error or could not be reached."""


# What a failed call raises once the SDK has given up retrying: an error response, no response,
# or a transport error (timeout, connection refused) from httpx.
SDK_ERRORS = (sdk_errors.OpenRouterError, sdk_errors.NoResponseError, httpx.HTTPError)

# Retries on 5XX and connection errors: 0.5 s doubling to at most 4 s, giving up after 20 s.
# The SDK's own default keeps retrying for up to an hour.
RETRY = RetryConfig("backoff", BackoffStrategy(500, 4000, 2, 20000), True)


@cache
def default_sdk() -> OpenRouter:
    """The one OpenRouter SDK client (and its httpx connection pool) shared by chat and embed.

    Each request times out after LLM_TIMEOUT_S seconds (default 120); embed passes a shorter one.
    """
    key = os.environ.get("OR_KEY")
    if not key:
        raise RuntimeError("OR_KEY is not set")
    timeout_s = float(os.environ.get("LLM_TIMEOUT_S", "120"))
    return OpenRouter(api_key=key, timeout_ms=int(timeout_s * 1000), retry_config=RETRY)


def configured_model() -> OpenRouterModel:
    """LLM_OPENROUTER_MODEL as a model ID, or the default. Unknown IDs fail."""
    value = os.environ.get("LLM_OPENROUTER_MODEL", DEFAULT_MODEL)
    try:
        return OpenRouterModel(value)
    except ValueError:
        raise RuntimeError(
            f"LLM_OPENROUTER_MODEL={value!r} is not one of {[m.value for m in OpenRouterModel]}"
        ) from None


class OpenRouterClient:
    """`chat(messages) -> str` and `stream(messages) -> Iterator[str]` over OpenAI-style messages."""

    def __init__(self, model: OpenRouterModel | None = None, sdk: OpenRouter | None = None):
        self.model = model or configured_model()
        self.sdk = sdk or default_sdk()

    def chat(self, messages: list[dict]) -> str:
        start = time.monotonic()
        with self._span(messages) as span:
            try:
                res = self.sdk.chat.send(model=self.model, messages=messages)
            except SDK_ERRORS as e:
                raise OpenRouterError(str(e)) from e
            if not res.choices:
                raise OpenRouterError("OpenRouter returned no choices")
            answer = _text(res.choices[0].message.content)
            _record(span, res.model, res.usage, answer, time.monotonic() - start)
            return answer

    def stream(self, messages: list[dict]) -> Iterator[str]:
        start = time.monotonic()
        with self._span(messages) as span:
            model, usage, parts = self.model.value, None, []
            try:
                with self.sdk.chat.send(model=self.model, messages=messages, stream=True,
                                        stream_options={"include_usage": True}) as events:
                    for chunk in events:
                        if chunk.error:
                            raise OpenRouterError(
                                f"OpenRouter stream error {chunk.error.code}: {chunk.error.message}")
                        model, usage = chunk.model or model, chunk.usage or usage
                        for choice in chunk.choices:
                            if choice.delta.content:
                                parts.append(choice.delta.content)
                                yield choice.delta.content
            except SDK_ERRORS as e:
                raise OpenRouterError(str(e)) from e
            _record(span, model, usage, "".join(parts), time.monotonic() - start)

    @contextmanager
    def _span(self, messages: list[dict]):
        """The LLM span and the `llm.chat` operation around one call; yields the span."""
        model = self.model.value
        attributes = {
            SpanAttributes.OPENINFERENCE_SPAN_KIND: OpenInferenceSpanKindValues.LLM.value,
            SpanAttributes.LLM_MODEL_NAME: model,
            SpanAttributes.INPUT_VALUE: json.dumps(messages, default=str),
            SpanAttributes.INPUT_MIME_TYPE: OpenInferenceMimeTypeValues.JSON.value,
        }
        vendor = model.split("/", 1)[0]
        if vendor in _PROVIDERS:
            attributes[SpanAttributes.LLM_PROVIDER] = vendor
        with (_tracer.start_as_current_span("openrouter.chat", attributes=attributes) as span,
              operation("llm.chat", model=model)):
            yield span


def _record(span, model: str | None, usage, answer: str, seconds: float) -> None:
    """Puts the answer, the model OpenRouter used, tokens and billed cost on the span."""
    span.set_attribute(SpanAttributes.OUTPUT_VALUE, answer)
    if model:
        span.set_attribute(SpanAttributes.LLM_MODEL_NAME, model)
    if not usage:
        return
    prompt, completion = usage.prompt_tokens_details, usage.completion_tokens_details
    costs = usage.cost_details
    values = {
        SpanAttributes.LLM_TOKEN_COUNT_PROMPT: usage.prompt_tokens,
        SpanAttributes.LLM_TOKEN_COUNT_COMPLETION: usage.completion_tokens,
        SpanAttributes.LLM_TOKEN_COUNT_TOTAL: usage.total_tokens,
        SpanAttributes.LLM_TOKEN_COUNT_PROMPT_DETAILS_CACHE_READ: prompt and prompt.cached_tokens,
        SpanAttributes.LLM_TOKEN_COUNT_PROMPT_DETAILS_CACHE_WRITE: prompt and prompt.cache_write_tokens,
        SpanAttributes.LLM_TOKEN_COUNT_COMPLETION_DETAILS_REASONING: completion and completion.reasoning_tokens,
        SpanAttributes.LLM_COST_TOTAL: usage.cost,
        SpanAttributes.LLM_COST_PROMPT: costs and costs.upstream_inference_prompt_cost,
        SpanAttributes.LLM_COST_COMPLETION: costs and costs.upstream_inference_completions_cost,
    }
    # The SDK marks absent fields as None or `Unset`; keep only real numbers.
    span.set_attributes({k: v for k, v in values.items() if isinstance(v, (int, float))})
    log.info("model=%s input_tokens=%d output_tokens=%d cost_usd=%s latency_s=%.2f", model,
             usage.prompt_tokens, usage.completion_tokens, usage.cost or None, seconds)


def _text(content) -> str:
    """Message content is a string, or a list of parts of which only text parts are kept."""
    if content is None or isinstance(content, str):
        return content or ""
    return "".join(getattr(part, "text", "") or "" for part in content)
