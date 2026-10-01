# Configuration

All configuration comes from environment variables. No credentials or keys in the repo.

| Variable | Purpose |
|---|---|
| `ORCHESTRATOR_PORT` | In use. Port the server listens on, default `8000` |
| `ORCHESTRATOR_BACKEND` | In use. What answers the route: `agent` (default) or `stub`, nothing else (`BackendName` in `backends.py`) |
| `AGENT_ADDRESS` | In use. The agent service's gRPC address, default `127.0.0.1:8002` (read by `contracts.agent.AgentClient`). The agent's own settings (OpenRouter key, models, judge, similarity floor) are the agent's: `../../agent/README.md#configuration` |
| `PHOENIX_COLLECTOR_ENDPOINT` | In use. Where spans are sent, default `http://localhost:6006` (see `../../docs/telemetry.md`) |
| `METRICS_COLLECTOR_ENDPOINT` | In use. Where metrics are sent (Grafana), default `http://localhost:4318` |
| `METRICS_ENABLED`, `TRACING_ENABLED` | In use. `false` turns metrics or tracing off (tests do this) |
| `ORCHESTRATOR_API_KEY` | In use. If set, every route except `/healthz` requires `Authorization: Bearer <key>`; unset, the API is open. `OrchestratorClient` sends it too |
| `ORCHESTRATOR_URL` | In use by callers, not the server: `OrchestratorClient`'s base URL (`integration_tests/`, `eval/`), default `http://127.0.0.1:8000` |

## Routes

One route, `personal-rag-v0.1`, fixed as `ROUTE` in `schemas.py` (see `contract.md`). What answers it is
`ORCHESTRATOR_BACKEND`.

## Values recorded with each run

Each request's spans carry `run.id` and `config.hash`, plus the slice of configuration this
service uses. The attribute names are in `../../docs/telemetry.md`.
