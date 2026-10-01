"""Query server: the `search.v1.Search` gRPC service from ../../../proto (contracts.search.v1).

Hybrid retrieval: a vector ranking (cosine similarity to the embedded query) and a BM25 ranking
(keyword match), fused with reciprocal rank fusion (k=60). A request may name one collection; both
rankings then cover only its notes.

Metrics (observability/, sent to Grafana): each query is the `search.query` operation (count,
latency, outcome; an invalid request is an `error`, a failed embedding a `fault`), and its steps
are timed with `@timed`: `search.embed`, `search.vector`, `search.bm25`, `search.fuse` (`ml.time`).
"""

from concurrent import futures

import grpc
from common.log import get_logger
from contracts.search.v1 import search_pb2, search_pb2_grpc
from llm import embed
from observability import UserError, operation, timed

from search import bm25, config, store
from search.hybrid import rrf

log = get_logger("search.server")

# How many of each ranking go into the fusion.
CANDIDATES = 50
DEFAULT_K = 5  # the proto's default for an unset k
MAX_K = 50


class InvalidRequest(UserError):
    """The caller's request breaks the contract: answered INVALID_ARGUMENT, counted as an error."""


@timed("search.embed")
def embed_query(query: str) -> list[float]:
    return embed(query, model=config.EMBED_MODEL).vector


@timed("search.vector")
def vector_rank(conn, vector: list[float], collection: str) -> list[tuple[str, float, str]]:
    """Every note of the collection with its cosine similarity to `vector`, best first."""
    return store.notes(conn, vector, config.EMBED_MODEL, collection)


@timed("search.bm25")
def keyword_rank(content: dict[str, str], query: str) -> list[tuple[str, float]]:
    return bm25.rank(content, query)


@timed("search.fuse")
def fuse(rankings: list[list[str]]) -> list[tuple[str, float]]:
    return rrf(rankings)


class SearchService(search_pb2_grpc.SearchServicer):
    def __init__(self, conn):
        self.conn = conn

    def Query(self, request: search_pb2.QueryRequest, context) -> search_pb2.QueryResponse:
        try:
            with operation("search.query"):
                return self._query(request)
        except InvalidRequest as e:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(e))

    def _query(self, request: search_pb2.QueryRequest) -> search_pb2.QueryResponse:
        k = request.k or DEFAULT_K
        if not request.query:
            raise InvalidRequest("query must not be empty")
        if not 1 <= k <= MAX_K:
            raise InvalidRequest(f"k must be 1 to {MAX_K}, got {request.k}")
        if request.collection and request.collection not in config.collections():
            raise InvalidRequest(
                f"collection {request.collection!r} is not indexed; indexed: {[c.value for c in config.collections()]}")
        vector = embed_query(request.query)
        rows = vector_rank(self.conn, vector, request.collection)
        content = {p: c for p, _, c in rows}
        similarity = {p: s for p, s, _ in rows}
        keyword = keyword_rank(content, request.query)
        fused = fuse([[p for p, _, _ in rows[:CANDIDATES]], [p for p, _ in keyword[:CANDIDATES]]])
        bm25_score = dict(keyword)
        return search_pb2.QueryResponse(results=[
            search_pb2.Result(path=p, score=s, content=content[p], similarity=similarity[p],
                              bm25=bm25_score.get(p, 0.0))
            for p, s in fused[:k]
        ])


def serve(conn, port: int) -> None:
    """Serve until the process is stopped."""
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    search_pb2_grpc.add_SearchServicer_to_server(SearchService(conn), server)
    server.add_insecure_port(f"127.0.0.1:{port}")
    server.start()
    log.info("serving search.v1.Search on 127.0.0.1:%d", port)
    server.wait_for_termination()
