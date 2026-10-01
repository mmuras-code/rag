#!/usr/bin/env bash
# Stop whatever listens on a TCP port and wait until the port is free.
# Usage: stop-port.sh <name> <port>
set -euo pipefail
name=$1 port=$2

pids=$(lsof -tiTCP:"$port" -sTCP:LISTEN || true)
if [[ -z $pids ]]; then echo "$name not running"; exit 0; fi
kill $pids
for _ in $(seq 10); do
    lsof -tiTCP:"$port" -sTCP:LISTEN >/dev/null || { echo "stopped $name"; exit 0; }
    sleep 1
done
echo "$name still listening on $port after 10 s" >&2
exit 1
