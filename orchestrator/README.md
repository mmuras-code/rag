# orchestrator

The backend Open WebUI connects to. Thin: it speaks the OpenAI-compatible API and hands each
request to the agent.

Status: minimal. `just run` serves `/v1/models` and `/v1/chat/completions` (streaming and not),
plus an unauthenticated liveness check, `GET /healthz`; `just dev` does the same and restarts on code changes. `just up` runs it in the background (log in `logs/orchestrator.log` at the `rag/` root); `just down` stops whatever serves the port.
One route, `personal-rag-v0.1` (`ROUTE` in `schemas.py`), shown as one model in Open WebUI's picker. What answers it is injected with
the `backend` FastAPI dependency in `src/orchestrator/backends.py`, chosen by `ORCHESTRATOR_BACKEND`. There are exactly two, the `BackendName` enum:

- `agent` (default): the agent service (`../agent/`: decide whether notes are needed, hybrid
  search over the notes, answer, judge, retry), called over gRPC through the client generated
  from its contract (`contracts.agent.AgentClient`, wrapped by `AgentBackend` in
  `src/orchestrator/clients/agent_client.py`). This project does not import `agent`. Needs the
  agent and search services running (`just agent up`, `just search up` from the `rag/` root);
  the agent holds the OpenRouter key and its own settings.
- `stub`: calls nothing and always replies "This is the stub backend." (`src/orchestrator/clients/stub_client.py`).
  For testing the wiring without a model.

A backend with a `stream(messages)` method is streamed piece by piece; others (the stub) are sent
as one chunk. The agent's `Run` stream sends a `Progress` event every 3 seconds while it works,
then the `Answer`; `AgentBackend` turns them into a counter (`1`, `2`, `3`, ...) and the answer, so Open WebUI shows it is alive during the 10-20 second run. Drafts are never
streamed.

If the backend fails after a stream has started, the client gets an error event (the same body as
the 503) and `data: [DONE]`, and the exception is raised once the response is complete, so it is
still counted (`EventStream` in `responses.py`).

Telemetry: a span per request (Phoenix) and the `orchestrator.http`
operation metrics, with outcome error (4xx), fault (503 from a `ServiceFault`) or failure (500), in
Grafana. The backend's answer is timed into `ml.time` as `orchestrator.answer` (a plain request)
or `orchestrator.stream` (a streamed one); see [`../docs/telemetry.md`](../docs/telemetry.md).

## Layout

```
src/orchestrator/
  app.py         FastAPI app: GET /healthz, GET /v1/models and POST /v1/chat/completions
  backends.py    Backend protocol, BackendName enum (agent, stub), the `backend` dependency
  schemas.py     request bodies (ChatRequest, Message)
  responses.py   response bodies: whole completion, SSE stream (EventStream), errors
  auth.py        optional API key check (ORCHESTRATOR_API_KEY)
  client.py      OrchestratorClient: for callers (integration_tests/, eval/), not used by the server
  clients/       agent_client.py (AgentBackend over the generated gRPC client), stub_client.py
```

## Function

- `/v1/chat/completions` with SSE streaming, and `/v1/models`.
- `/healthz` for liveness: no key, no dependency checks.
- Each entry in `/v1/models` is a route; there is one, `personal-rag-v0.1`.
- The request's trace id is its request id. The call to the agent carries the trace in its gRPC
  metadata (`traceparent`, added by the `contracts` wrapper), so the agent's spans join it. An
  agent that is down, times out or reports a dependency down (UNAVAILABLE) is `AgentUnavailable`,
  a `ServiceFault`, answered 503. The
  completion `id` is `chatcmpl-<trace id>`, so a caller can find the request's trace in Phoenix;
  `OrchestratorClient.reply()` returns it as `Reply.trace_id` (`eval/` reads cost this way).
- Stateless: Open WebUI sends the full message history with every request.
- Streams only the final answer (or short status updates), never intermediate drafts.

## Open WebUI settings

Open WebUI's auxiliary requests (chat titles, tags, follow-ups, autocomplete, retrieval queries)
would each run the whole agent loop. They are turned off in `../webui/compose.yaml`, along with
the Ollama connection; see `docs/runbook.md`.

## Docs

- `docs/contract.md`: the Open WebUI edge (OpenAI-compatible) and the agent edge, with the
  request flow.
- `docs/config.md`: environment variables and routes.
- `docs/runbook.md`: connecting Open WebUI, its settings, debugging a request.

Decisions local to this service will go in `docs/decisions/` once there are any. The open
questions are listed at the end of `docs/contract.md`.
