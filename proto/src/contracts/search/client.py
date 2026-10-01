"""Client for the search service: a thin wrapper over the generated stub (`v1/search_pb2_grpc`).

It only fills in the address, the deadline and the request message, and sends each call through
the interceptors given to the constructor (`Request`/`Interceptor` in ../interceptors.py, e.g.
`Retry`). Errors are the stub's own `grpc.RpcError` (`code()` is e.g. UNAVAILABLE when search is
down, INVALID_ARGUMENT for a bad k). The service embeds the query itself, with the same model it
used for the notes, so callers send plain text.
"""

import os
from collections.abc import Sequence

from contracts.interceptors import Interceptor, bind, make_channel
from contracts.search.v1 import search_pb2
from contracts.search.v1.search_pb2 import QueryRequest, Result
from contracts.search.v1.search_pb2_grpc import SearchStub

DEFAULT_ADDRESS = "127.0.0.1:8001"
SERVICE = search_pb2.DESCRIPTOR.services_by_name["Search"]


class SearchClient:
    def __init__(self, address: str | None = None, *, timeout: float = 30,
                 interceptors: Sequence[Interceptor] = (), options: Sequence = ()):
        """`options` are gRPC channel options, over `DEFAULT_CHANNEL_OPTIONS`."""
        self.address = address or os.environ.get("SEARCH_ADDRESS", DEFAULT_ADDRESS)
        self.timeout = timeout
        stub = SearchStub(make_channel(self.address, options))
        self._query = bind(stub, SERVICE, "Query", interceptors)

    def query(self, text: str, k: int = 5, collection: str = "") -> list[Result]:
        """Best match first. `collection` limits the search to one collection; empty searches all."""
        return list(self._query(QueryRequest(query=text, k=k, collection=collection), self.timeout).results)
