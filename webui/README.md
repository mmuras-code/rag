# webui

Runs [Open WebUI](https://github.com/open-webui/open-webui) in Docker, pointed at the
`orchestrator/` backend. Configuration only: no code and no tests.

The environment variables in `compose.yaml` were checked against Open WebUI v0.11.4, the pinned
image.

## Run

```
cp .env.example .env    # optional, defaults work
just up                 # http://localhost:3000
just logs
just down
```

The first account you create becomes the admin.

## Config

| Variable | Default | Meaning |
|---|---|---|
| `WEBUI_PORT` | `3000` | Host port for the UI |
| `WEBUI_IMAGE_TAG` | `v0.11.4` | Open WebUI image tag, pinned to a release to avoid surprise upgrades. Change it, then `just pull` and `just up` |
| `ORCHESTRATOR_BASE_URL` | `http://host.docker.internal:8000/v1` | Orchestrator's OpenAI-compatible base URL |
| `ORCHESTRATOR_API_KEY` | `dummy` | Key sent to the orchestrator; any string if it does not check |

- Inside the container `localhost` is the container itself, so the orchestrator on the host is
  reached as `host.docker.internal`.
- `ENABLE_PERSISTENT_CONFIG=false` makes env vars win over settings saved in the UI on every
  start, so changing `.env` or `compose.yaml` and running `just up` takes effect. Settings changed
  in the admin UI are not kept across restarts.

Already set in `compose.yaml` (not in `.env`):

| Setting | Value | Why |
|---|---|---|
| `ENABLE_OLLAMA_API` | `false` | No Ollama; models come only from the orchestrator |
| `DEFAULT_MODELS` | `personal-rag-v0.1` | The orchestrator's one route is selected in new chats |
| `ENABLE_TITLE_GENERATION`, `ENABLE_TAGS_GENERATION`, `ENABLE_FOLLOW_UP_GENERATION`, `ENABLE_AUTOCOMPLETE_GENERATION`, `ENABLE_RETRIEVAL_QUERY_GENERATION` | `false` | Each auxiliary request would run the whole paid agent loop |
- Chats, users and uploads are stored in `./data` (git-ignored). Back up that directory.

## Docs

Connecting to the orchestrator and debugging a request: `../orchestrator/docs/runbook.md`.
