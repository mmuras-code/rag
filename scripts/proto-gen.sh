#!/usr/bin/env bash
# Generate the Python code for every .proto under proto/src: messages (*_pb2.py, *_pb2.pyi) and
# gRPC stubs (*_pb2_grpc.py), next to each .proto. With --check, generate into a temporary
# directory and fail if it differs from what is checked in.
# Usage: proto-gen.sh [--check]   (run from proto/, inside its uv environment)
set -euo pipefail
src=$(pwd)/src
out=$src
if [[ ${1:-} == --check ]]; then
    out=$(mktemp -d)
    trap 'rm -rf "$out"' EXIT
fi
cd "$src"
python -m grpc_tools.protoc -I . --python_out="$out" --pyi_out="$out" --grpc_python_out="$out" \
    $(find contracts -name '*.proto' | sort)
[[ ${1:-} == --check ]] || exit 0
stale=0
for f in $(cd "$out" && find contracts -name '*_pb2*' | sort); do
    cmp -s "$out/$f" "$src/$f" || { echo "stale: proto/src/$f" >&2; stale=1; }
done
[[ $stale == 0 ]] || { echo "run 'just proto generate' and commit the result" >&2; exit 1; }
echo "generated code is up to date"
