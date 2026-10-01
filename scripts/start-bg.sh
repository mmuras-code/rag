#!/usr/bin/env bash
# Run a command in the background and wait until a URL answers.
# Usage: start-bg.sh <name> <health-url> <timeout-seconds> -- <command...>
# <health-url> is an HTTP URL (must answer 2xx) or tcp://host:port (must accept connections; for
# gRPC services, which listen only once they are ready to serve).
# Log files follow one pattern, <name>.<stream>.<creation time>.log (common.log.FILE_NAME), so
# common.log_cleaner can delete old ones. The service logs through common.log to
# logs/<name>.app.<time>.log (logs/<name>.log is a symlink to the current file); LOG_STDERR=false
# keeps those lines off the console, so logs/<name>.console.<time>.log (symlink
# logs/<name>.console.log) holds only what bypasses logging, such as a crash at startup. Both are
# streamed while waiting.
# Skipped if the URL already answers; fails if the command exits before it does.
set -euo pipefail
name=$1 url=$2 timeout=$3
shift 3
[[ ${1:-} == -- ]] && shift

probe() {
    if [[ $url == tcp://* ]]; then
        local hostport=${url#tcp://}
        (exec 3<>"/dev/tcp/${hostport%:*}/${hostport##*:}") 2>/dev/null
    else
        curl -sf -o /dev/null "$url"
    fi
}

if probe; then echo "$name already running"; exit 0; fi

logs=$(cd "$(dirname "$0")/.." && pwd)/logs
log=$logs/$name.log
console=$logs/$name.console.log
console_file=$name.console.$(date +%Y-%m-%dT%H-%M-%S).log
echo "starting $name (log in $log, console output in $console)"
mkdir -p "$logs"
ln -sfn "$console_file" "$console"
LOG_STDERR=false nohup "$@" > "$logs/$console_file" 2>&1 &
pid=$!
tail -q -n 0 -F "$log" "$console" 2>/dev/null > >(sed -u "s/^/[$name] /") &
tail_pid=$!
trap 'kill $tail_pid 2>/dev/null' EXIT

for _ in $(seq "$timeout"); do
    probe && { echo "$name is up"; exit 0; }
    kill -0 $pid 2>/dev/null || { echo "$name exited during startup; see $console" >&2; exit 1; }
    sleep 1
done
echo "$name did not come up in $timeout s; see $log" >&2
exit 1
