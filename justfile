# Cross-cutting recipes for rag/. Service recipes are modules: `just <service> <recipe>`.
# See docs/decisions/0002-just-as-task-runner.md.

mod common
mod llm
mod proto
mod search
mod agent
mod orchestrator
mod webui
mod observability
mod integration_tests
mod eval

scripts := justfile_directory() / "scripts"

default:
    @just --list --list-submodules

# Set up a fresh clone: install the missing tools.
setup: tools

# Install the machine requirements from docs/requirements.md that are missing.
tools:
    #!/usr/bin/env bash
    set -euo pipefail
    if ! command -v brew >/dev/null 2>&1; then
        echo "Homebrew not found. Install it from https://brew.sh, then rerun." >&2
        exit 1
    fi
    if [[ ! -d /Applications/Docker.app ]]; then
        brew install --cask docker-desktop
        echo "Open Docker Desktop once to accept the license before 'just webui up'."
    fi

# Start the whole stack in order: the log cleaner, Docker Desktop, Phoenix, search, agent, orchestrator, Open WebUI. Each service's `up` does the work.
up:
    just common log-cleaner-up
    @{{scripts}}/docker-desktop.sh start
    just observability up
    just search up
    just agent up
    just orchestrator up
    just webui up

# Stop the whole stack in reverse order, then quit Docker Desktop if no other container runs, then the log cleaner. Volumes and data are kept.
down:
    just webui down
    just orchestrator down
    just agent down
    just search down
    just observability down
    @{{scripts}}/docker-desktop.sh stop
    just common log-cleaner-down
