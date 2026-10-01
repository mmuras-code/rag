# Runbook

## Connect Open WebUI

1. Start the orchestrator (`just up` waits on `GET /healthz`) and check that `GET /v1/models`
   lists the `personal-rag-v0.1` route (with the key, if `ORCHESTRATOR_API_KEY` is set).
2. Start Open WebUI (`just webui up` from the `rag/` root). The connection to the orchestrator is
   already set in `../../webui/compose.yaml` (`OPENAI_API_BASE_URL`, `OPENAI_API_KEY`).
3. `agent` shows up in the model picker and is the default for new chats.

## Open WebUI settings

Already set in `../../webui/compose.yaml`; nothing to change in the UI. Because
`ENABLE_PERSISTENT_CONFIG=false`, these env values win on every start, and changes made in the
admin UI are lost on restart.

- **Ollama:** off (`ENABLE_OLLAMA_API=false`); models come only from the orchestrator.
- **Default model:** `personal-rag-v0.1` (`DEFAULT_MODELS`).
- **Auxiliary requests:** Open WebUI would send extra requests through the model for chat
  titles, tags, follow-up suggestions, autocomplete and retrieval queries, and each would run the
  whole paid agent loop. All are off (`ENABLE_TITLE_GENERATION`, `ENABLE_TAGS_GENERATION`,
  `ENABLE_FOLLOW_UP_GENERATION`, `ENABLE_AUTOCOMPLETE_GENERATION`,
  `ENABLE_RETRIEVAL_QUERY_GENERATION`, all `false`).
- **Built-in RAG:** runs only on files or knowledge bases attached to a chat. Don't attach any,
  or it runs alongside `search/`.

## Debugging a request

- Every request has a request id, which is its trace id. Find the trace in Phoenix to see each
  step, token counts, iterations and verifier results.
- To see how a request ended, look at `agent.termination_reason` on the agent's root span
  (`passed`, `iteration_limit`, `judge_unavailable` or `budget`).
- A very slow first token is expected: the loop runs several LLM calls before anything streams.

## Common failures

- Open WebUI cannot reach the service: wrong base URL or port, or the orchestrator is not
  running (`curl http://127.0.0.1:8000/healthz`).
- 503 `agent: ...`: the agent service is not running (`just agent up`), or it reported a
  dependency down (search or OpenRouter; the message says which). `/healthz` does not check the
  agent. The agent's log is `logs/agent.log`.
- 401: `ORCHESTRATOR_API_KEY` differs between the orchestrator's and Open WebUI's environment.
- A stream that ends with an `{"error": ...}` event: the backend failed midway; the request is
  counted as a fault or failure in Grafana, and its trace is in Phoenix.
