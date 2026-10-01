# Conventions

## Layout

- One directory per service or library. Each has a `README.md` (purpose, how to run, config,
  links) and a `docs/` directory for its contract, config reference, runbook and local decisions.
- Each service has its own `pyproject.toml`, its own dependencies and its own `tests/`.
- Cross-cutting facts live once, in the root `docs/`. Service docs link to them.
- Shell logic for recipes lives in the root `scripts/` (generic start, wait and stop helpers);
  recipes echo and call them (see `decisions/0002-just-as-task-runner.md`).

## Documentation

- Docs live next to the code they describe, and change in the same edit.
- A service's contract (endpoints, request and response shapes) is its public API. Generate it
  from the code where possible and check that the committed copy is not stale.
- Decisions are short ADRs in `decisions/` (root for cross-service, service `docs/` for local):
  the choice, the alternatives, the reason.
- Diagrams are always Mermaid fenced blocks in Markdown files, so PyCharm renders them. This
  is a hard requirement: no ASCII art, no images. Directory listings are not diagrams.
- System documentation is in this repo. Learning notes about ML concepts go in the Obsidian
  vault, not here.

## Code

- Log through `common.log`: `get_logger(name)` in modules, `setup_logging(service)` once per
  service entry point, never the `logging` module directly. Files, rolling and settings:
  `../common/README.md#logging`.
- Run things through `just` recipes (see `decisions/0002-just-as-task-runner.md`), and document
  commands as `just <recipe>`.
- Every service's interface is a `.proto` in `../proto/src/contracts/<service>/v1/`, served over
  gRPC. Callers use the client generated from it, through the thin wrapper in
  `contracts.<service>.client`; never a hand-written copy of the interface, and never another
  service's project. After editing a `.proto`, run `just proto generate` and commit the generated
  code (see `decisions/0005-grpc-generated-clients.md`).
- The orchestrator's OpenAI-compatible edge is the only HTTP server: a FastAPI app wired with
  `Depends`; code below it uses plain constructor injection and never imports FastAPI (see
  `decisions/0004-fastapi-for-http-layers.md`).
- Configuration and secrets come from environment variables. No credentials in the repo.
- All code in `rag/` is Python (see `decisions/0003-python-for-all-services.md`). `infra/` is a
  separate TypeScript project and is not covered. The dev scripts in `scripts/` are bash.
- No provider SDK outside `llm/`.
- `tests/` are pass/fail correctness checks. Quality scores over time belong to `eval/`.
- Every service emits traces using the shared helper in `observability/` and the attribute
  names in `telemetry.md`.
- The Obsidian vault is read-only for everything in `rag/`.
