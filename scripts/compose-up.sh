#!/usr/bin/env bash
# `docker compose up -d` in the current directory, then wait until a URL answers.
# Usage: compose-up.sh <name> <health-url> <timeout-seconds> [compose service...]
# Skipped if the URL already answers.
set -euo pipefail
name=$1 url=$2 timeout=$3
shift 3

if curl -sf -o /dev/null "$url"; then echo "$name already running"; exit 0; fi

docker compose up -d "$@"
for _ in $(seq "$timeout"); do
    curl -sf -o /dev/null "$url" && { echo "$name is up"; exit 0; }
    sleep 1
done
echo "$name did not come up in $timeout s; see 'docker compose logs' in $PWD" >&2
exit 1
