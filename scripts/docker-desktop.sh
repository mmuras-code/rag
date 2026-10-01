#!/usr/bin/env bash
# Start or quit Docker Desktop.
# Usage: docker-desktop.sh start | stop
# `start` waits until the daemon answers. `stop` leaves Docker running if any container still
# runs, since those belong to something other than this stack.
set -euo pipefail

case ${1:-} in
start)
    docker info >/dev/null 2>&1 && exit 0
    echo "starting Docker Desktop"
    open -a Docker
    for _ in $(seq 120); do docker info >/dev/null 2>&1 && exit 0; sleep 1; done
    echo "Docker did not start in 120 s" >&2
    exit 1
    ;;
stop)
    if ! docker info >/dev/null 2>&1; then echo "Docker Desktop not running"; exit 0; fi
    running=$(docker ps -q | wc -l | tr -d ' ')
    if [[ $running != 0 ]]; then
        echo "leaving Docker Desktop running: $running other container(s) still up (docker ps)"
        exit 0
    fi
    osascript -e 'quit app "Docker"'
    echo "quit Docker Desktop"
    ;;
*)
    echo "usage: $0 start | stop" >&2
    exit 2
    ;;
esac
