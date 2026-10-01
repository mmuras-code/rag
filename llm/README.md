# llm

Provider-agnostic client for chat, streaming and embeddings. The only place in `rag/` that talks to model providers.

Status: `embed` and `OpenRouterClient` (chat and streaming), both through OpenRouter, are built; the shared
`chat`/`stream` interface and roles are not.

## Function

- One interface for every caller: `chat`, `stream`, `embed`.
- Roles in config map to models: `generator`, `judge`, `embedder`. The judge is never one of
  the candidates being compared.
- Provider: [OpenRouter](https://openrouter.ai) for chat, streaming and embeddings, through the
  official `openrouter` SDK. One key reaches many vendors; models are named `<vendor>/<model>`.
  `OpenRouterClient(model=None).chat(messages) -> str` and `.stream(messages) -> Iterator[str]`
  take OpenAI-style messages, the same shape as the orchestrator's `Backend`. Models are the
  `OpenRouterModel` enum (`HAIKU`, `SONNET`, `OPUS`, `GPT_4O`); Haiku is the default.
  `embed(text, model=None) -> Embedding(vector, token_count, truncated)` uses OpenRouter's
  embeddings API. Input whose token count reaches `LLM_EMBED_MAX_TOKENS` is flagged as
  truncated: providers either cut it silently or reject it. The default model is
  `DEFAULT_EMBED_MODEL`, which `search` imports instead of repeating it.
- One SDK client (`default_sdk()`, cached) is shared by chat and embed, so calls reuse one httpx
  connection pool. Requests time out after `LLM_TIMEOUT_S` (chat) or `LLM_EMBED_TIMEOUT_S`
  (embed). 5XX and connection errors are retried with backoff (0.5 s doubling to 4 s) for at most
  20 s; the SDK's own default retries for up to an hour.
- Logs input and output tokens, cost and latency per chat or stream call (not per embedding).
- Telemetry (through `../observability/`): each chat or stream call is an OpenInference LLM span
  (`openrouter.chat`) with the model OpenRouter used, token counts and the billed cost
  (`llm.cost.total`), so Phoenix shows cost per call, trace and experiment; and the `llm.chat`
  operation metric (`model`). See [`../docs/telemetry.md`](../docs/telemetry.md).
- Errors: once retries are spent, any failure from chat, stream or embed (an error response, a
  timeout or another transport error, or an empty `choices`/`data`) raises `OpenRouterError`, a
  `ServiceFault`.
- Idea, not built: a response cache keyed on model, prompt and parameters.

## Type

Library first. A gateway service is only worth it if several services need shared keys, rate
limits or cost tracking.

## Library

```
just install            # uv sync
just test               # uv run pytest
just openrouter "Hi"    # one chat through OpenRouterClient (needs OR_KEY)
just embed "Hi"         # one embedding: token count, dimensions, truncated
```

## Config

| Variable | Default | Meaning |
|---|---|---|
| `OR_KEY` | none, required | OpenRouter key for `OpenRouterClient` and `embed`; put it in `.env`, never the repo |
| `LLM_EMBED_MODEL` | `openai/text-embedding-3-small` | Embedding model used by `embed` |
| `LLM_EMBED_MAX_TOKENS` | `8191` | The embedding model's input limit; input at or over it is reported as truncated |
| `LLM_TIMEOUT_S` | `120` | Request timeout in seconds for chat and streaming (the shared client's default) |
| `LLM_EMBED_TIMEOUT_S` | `30` | Request timeout in seconds for `embed` |
| `LLM_OPENROUTER_MODEL` | `anthropic/claude-haiku-4.5` | Model `OpenRouterClient` calls when none is passed; must be an `OpenRouterModel` value |

## Docs

`docs/` will hold the config reference and provider notes. See `../docs/conventions.md`.
