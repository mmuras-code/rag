#!/usr/bin/env bash
# Stop a process started by start-pid.sh and remove its pid file.
# Usage: stop-pid.sh <name>
set -euo pipefail
name=$1
pidfile=$(cd "$(dirname "$0")/.." && pwd)/logs/$name.pid

if [[ ! -f $pidfile ]] || ! kill -0 "$(cat "$pidfile")" 2>/dev/null; then
    rm -f "$pidfile"; echo "$name not running"; exit 0
fi
pid=$(cat "$pidfile")
kill "$pid"
for _ in $(seq 10); do
    kill -0 "$pid" 2>/dev/null || { rm -f "$pidfile"; echo "stopped $name"; exit 0; }
    sleep 1
done
echo "$name (pid $pid) still running after 10 s" >&2
exit 1
