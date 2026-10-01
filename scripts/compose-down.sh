#!/usr/bin/env bash
# `docker compose down` in the current directory; volumes are kept.
# Usage: compose-down.sh <name>
# Skipped when Docker is not running, since then none of its containers are either.
set -euo pipefail
name=$1

if ! docker info >/dev/null 2>&1; then echo "$name: Docker not running, nothing to stop"; exit 0; fi
docker compose down
