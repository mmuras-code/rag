# Requirements

Tools that must be installed on the machine before running the services. `just setup` at the
`rag/` root installs Docker Desktop if it is missing; install Homebrew, `just` and `uv` by hand.

| Tool | Needed by | Why | Install (macOS) |
|---|---|---|---|
| Docker Desktop | `webui/`, `observability/`, `search/` | Runs Open WebUI, Phoenix, Grafana and pgvector (`search/`'s compose file) as containers (`docker compose`) | `brew install --cask docker-desktop` |
| `uv` | every project | Python package and virtualenv manager; each project has its own `pyproject.toml` and `uv.lock` | `brew install uv` (or the official installer: `curl -LsSf https://astral.sh/uv/install.sh \| sh`) |
| `just` | all services | Task runner; every command is documented as `just <recipe>` (see `decisions/0002-just-as-task-runner.md`) | `brew install just` |

## Accounts and keys

- An [OpenRouter](https://openrouter.ai) API key in `OR_KEY` is required by `llm/`,
  `search/` and `agent/` (and so by the orchestrator, which runs the agent). Every chat call goes
  through it, and so do embeddings today (a local ONNX model in `search/` is the planned
  replacement; see `plan.md`). Put it in each service's git-ignored `.env`, never the repo.

## Docker

- Docker Desktop must be running (the whale icon in the menu bar) before `just up` in `webui/`,
  `observability/` or `search/`. The root `just up` starts it if it is not running, and the
  root `just down` quits it if no other container is running.
  The first launch asks for permissions and to accept the license.
- Requires macOS 14 or later.
- Check it works: `docker version` and `docker compose version`.
- Images, containers and volumes live inside Docker Desktop's VM disk image, not in the repo.
  Open WebUI's own data is in `webui/data/` (git-ignored).
