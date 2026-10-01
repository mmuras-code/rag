from concurrent import futures
from unittest.mock import MagicMock

import grpc
import pytest
from contracts.search import SearchClient
from contracts.search.v1 import search_pb2_grpc
from contracts.search.v1.search_pb2 import QueryRequest
from llm import Embedding

from search import server as server_module
from search.server import SearchService


class Aborted(Exception):
    pass


def context():
    """A servicer context whose abort raises, as grpc's does."""

    def abort(code, details):
        raise Aborted(code)

    return MagicMock(abort=MagicMock(side_effect=abort))


def test_query_fuses_vector_and_bm25(monkeypatch):
    seen = {}

    def fake_embed(text, model):
        seen["text"] = text
        return Embedding([0.1], 3, False)

    # Vector ranking: a, b, c. BM25 on "pgvector": only c mentions it.
    rows = [("a.md", 0.9, "alpha"), ("b.md", 0.8, "beta"), ("c.md", 0.7, "pgvector pgvector")]
    monkeypatch.setattr(server_module, "embed", fake_embed)
    monkeypatch.setattr(server_module.store, "notes", lambda conn, vector, model, collection: rows)
    results = SearchService(None).Query(QueryRequest(query="pgvector", k=2), context()).results

    assert seen["text"] == "pgvector"
    # c: 1/(60+3) + 1/(60+1) beats a: 1/(60+1).
    assert [r.path for r in results] == ["c.md", "a.md"]
    c = results[0]
    assert c.similarity == 0.7 and c.bm25 > 0 and c.content == "pgvector pgvector"
    assert results[1].bm25 == 0.0


def test_unset_k_is_5(monkeypatch):
    monkeypatch.setattr(server_module, "embed", lambda text, model: Embedding([0.1], 1, False))
    rows = [(f"{i}.md", 1 - i / 10, "x") for i in range(8)]
    monkeypatch.setattr(server_module.store, "notes", lambda conn, vector, model, collection: rows)
    assert len(SearchService(None).Query(QueryRequest(query="q"), context()).results) == 5


@pytest.mark.parametrize("request_", [QueryRequest(query="q", k=-1), QueryRequest(query="q", k=51),
                                      QueryRequest(query=""), QueryRequest(k=3),
                                      QueryRequest(query="q", collection="finance")])
def test_invalid_request_is_invalid_argument(monkeypatch, request_):
    monkeypatch.setattr(server_module, "embed", lambda text, model: pytest.fail("must not embed"))
    with pytest.raises(Aborted) as e:
        SearchService(None).Query(request_, context())
    assert e.value.args[0] == grpc.StatusCode.INVALID_ARGUMENT


def test_over_grpc_through_the_generated_client(monkeypatch):
    monkeypatch.setattr(server_module, "embed", lambda text, model: Embedding([0.1], 1, False))
    monkeypatch.setattr(server_module.store, "notes", lambda conn, vector, model, collection: [("a.md", 0.9, "alpha")])
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=1))
    search_pb2_grpc.add_SearchServicer_to_server(SearchService(None), server)
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()
    try:
        client = SearchClient(f"127.0.0.1:{port}")
        assert [r.path for r in client.query("alpha", k=3)] == ["a.md"]
        with pytest.raises(grpc.RpcError) as e:
            client.query("alpha", k=51)
        assert e.value.code() == grpc.StatusCode.INVALID_ARGUMENT
    finally:
        server.stop(None)


def test_collection_is_passed_to_the_store(monkeypatch):
    seen = {}

    def notes(conn, vector, model, collection):
        seen["collection"] = collection
        return [("test/a.md", 0.9, "alpha")]

    monkeypatch.setattr(server_module, "embed", lambda text, model: Embedding([0.1], 1, False))
    monkeypatch.setattr(server_module.store, "notes", notes)
    SearchService(None).Query(QueryRequest(query="q", collection="test"), context())
    assert seen["collection"] == "test"
    SearchService(None).Query(QueryRequest(query="q"), context())
    assert seen["collection"] == ""
