import sys

from common.log import setup_logging
from observability import setup_telemetry

from search import config, store
from search.server import serve
from search.sync import sync

setup_logging("search")  # logs/search.<time>.log and stderr; see common/log.py

USAGE = "usage: python -m search {sync|serve} | python -m search query <text> [k] [collection]"

if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "query" and len(sys.argv) in (3, 4, 5):
        # Through the generated client, like any caller: needs the server running.
        from contracts.search import SearchClient

        k = int(sys.argv[3]) if len(sys.argv) >= 4 else 5
        for r in SearchClient().query(sys.argv[2], k=k, collection=sys.argv[4] if len(sys.argv) == 5 else ""):
            print(f"{r.score:.4f}  sim {r.similarity:.3f}  bm25 {r.bm25:.2f}  {r.path}")
        raise SystemExit
    if command not in ("sync", "serve"):
        raise SystemExit(USAGE)
    # Spans to Phoenix, metrics to Grafana, as service `search` on this pod; before the server is
    # built, so its gRPC instrumentation continues the caller's trace.
    setup_telemetry("search")
    conn = store.connect(config.DATABASE_URL)
    sync(conn)
    if command == "serve":
        serve(conn, config.PORT)
