"""Embeddings through OpenRouter's embeddings API, using its official SDK (`openrouter`).

The response reports the input token count. A count at or over LLM_EMBED_MAX_TOKENS is flagged
as truncated: depending on the provider, input over the model's limit is cut silently or rejected.
Uses the shared SDK client from `llm.openrouter`; each request times out after
LLM_EMBED_TIMEOUT_S seconds (default 30). A failure raises `OpenRouterError`.
"""

import os
from dataclasses import dataclass

from openrouter import OpenRouter

from llm.openrouter import SDK_ERRORS, OpenRouterError, default_sdk

DEFAULT_EMBED_MODEL = "openai/text-embedding-3-small"


@dataclass
class Embedding:
    vector: list[float]
    token_count: int
    truncated: bool


def embed(text: str, model: str | None = None, max_tokens: int | None = None,
          sdk: OpenRouter | None = None) -> Embedding:
    model = model or os.environ.get("LLM_EMBED_MODEL", DEFAULT_EMBED_MODEL)
    max_tokens = max_tokens or int(os.environ.get("LLM_EMBED_MAX_TOKENS", "8191"))
    timeout_ms = int(float(os.environ.get("LLM_EMBED_TIMEOUT_S", "30")) * 1000)
    sdk = sdk or default_sdk()
    try:
        res = sdk.embeddings.generate(model=model, input=text, encoding_format="float",
                                      timeout_ms=timeout_ms)
    except SDK_ERRORS as e:
        raise OpenRouterError(str(e)) from e
    if not res.data:
        raise OpenRouterError("OpenRouter returned no embedding")
    tokens = res.usage.prompt_tokens if res.usage else 0
    return Embedding(vector=res.data[0].embedding, token_count=tokens, truncated=tokens >= max_tokens)
