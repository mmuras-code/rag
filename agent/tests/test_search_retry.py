"""The agent's default search client is built with `Retry`: tested over real gRPC against an
in-process search server that fails with UNAVAILABLE before it answers."""

from concurrent import futures

import grpc
import pytest
from contracts.search.v1 import search_pb2, search_pb2_grpc
from contracts.search.v1.search_pb2 import Result

from agent.graph import SEARCH_ATTEMPTS, SearchUnavailable, build_graph, run
from test_graph import QUESTION, fakes


class FlakySearch(search_pb2_grpc.SearchServicer):
    def __init__(self, failures: int, code=grpc.StatusCode.UNAVAILABLE):
        self.failures, self.code, self.calls = failures, code, 0

    def Query(self, request, context):
        self.calls += 1
        if self.calls <= self.failures:
            context.abort(self.code, "restarting")
        return search_pb2.QueryResponse(results=[
            search_pb2.Result(path="rag/rrf.md", score=0.03, content="rrf body", similarity=0.6)])


@pytest.fixture
def search_server(monkeypatch):
    servers = []

    def start(servicer):
        server = grpc.server(futures.ThreadPoolExecutor(max_workers=2))
        search_pb2_grpc.add_SearchServicer_to_server(servicer, server)
        port = server.add_insecure_port("127.0.0.1:0")
        server.start()
        servers.append(server)
        monkeypatch.setenv("SEARCH_ADDRESS", f"127.0.0.1:{port}")  # read by the default client
        return servicer

    yield start
    for s in servers:
        s.stop(None)


def graph_with_default_search_client():
    """The real graph with fake models and the default search client (`search=None`)."""
    # `results` only tells the fake grade step which paths to keep; the notes come from the server.
    chat, calls, judge, _ = fakes('{"route": "ml", "query": "rrf"}', [80], [Result(path="rag/rrf.md")])
    return build_graph(chat, None, judge), calls


def test_search_failing_then_recovering_is_retried(search_server):
    search = search_server(FlakySearch(failures=SEARCH_ATTEMPTS - 1))
    graph, calls = graph_with_default_search_client()
    assert run(QUESTION, graph) == "answer 1"
    assert search.calls == SEARCH_ATTEMPTS
    assert "rag/rrf.md" in calls[0][0]["content"]  # the retried search's notes reached the answer


def test_search_still_down_after_every_attempt_is_search_unavailable(search_server):
    search = search_server(FlakySearch(failures=SEARCH_ATTEMPTS))
    graph, _ = graph_with_default_search_client()
    with pytest.raises(SearchUnavailable, match="UNAVAILABLE: restarting"):
        run(QUESTION, graph)
    assert search.calls == SEARCH_ATTEMPTS


def test_other_search_errors_are_not_retried(search_server):
    search = search_server(FlakySearch(failures=1, code=grpc.StatusCode.INVALID_ARGUMENT))
    graph, _ = graph_with_default_search_client()
    with pytest.raises(SearchUnavailable, match="INVALID_ARGUMENT"):
        run(QUESTION, graph)
    assert search.calls == 1
