#!/usr/bin/env bash
# Run a command in the background that serves no port, tracked by logs/<name>.pid.
# Usage: start-pid.sh <name> -- <command...>
# Console output goes to logs/<name>.console.<time>.log (symlink logs/<name>.console.log), the
# same pattern as start-bg.sh. Skipped if the pid file names a live process; fails if the command
# exits within a second.
set -euo pipefail
name=$1
shift
[[ ${1:-} == -- ]] && shift

logs=$(cd "$(dirname "$0")/.." && pwd)/logs
pidfile=$logs/$name.pid
if [[ -f $pidfile ]] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
    echo "$name already running (pid $(cat "$pidfile"))"; exit 0
fi

mkdir -p "$logs"
console_file=$name.console.$(date +%Y-%m-%dT%H-%M-%S).log
ln -sfn "$console_file" "$logs/$name.console.log"
LOG_STDERR=false nohup "$@" > "$logs/$console_file" 2>&1 &
pid=$!
sleep 1
kill -0 $pid 2>/dev/null || { echo "$name exited at startup; see $logs/$name.console.log" >&2; exit 1; }
echo $pid > "$pidfile"
echo "$name running (pid $pid, log in $logs/$name.log)"
