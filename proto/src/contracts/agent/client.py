"""Client for the agent service: a thin wrapper over the generated stub (`v1/agent_pb2_grpc`).

It only fills in the address, the deadline and the request message, and sends each call through
the interceptors given to the constructor (`Request`/`Interceptor` in ../interceptors.py). `Run`
streams, so an interceptor gets an iterator back from `proceed`. Errors are the stub's own
`grpc.RpcError` (`code()` is UNAVAILABLE when the agent or one of its dependencies is down).
"""

import os
from collections.abc import Iterable, Iterator, Sequence

from contracts.agent.v1 import agent_pb2
from contracts.agent.v1.agent_pb2 import Message, RunEvent, RunRequest
from contracts.agent.v1.agent_pb2_grpc import AgentStub
from contracts.interceptors import Interceptor, bind, close, make_channel

DEFAULT_ADDRESS = "127.0.0.1:8002"
SERVICE = agent_pb2.DESCRIPTOR.services_by_name["Agent"]


class AgentClient:
    def __init__(self, address: str | None = None, *, timeout: float = 600,
                 interceptors: Sequence[Interceptor] = (), options: Sequence = ()):
        """`options` are gRPC channel options, over `DEFAULT_CHANNEL_OPTIONS`."""
        self.address = address or os.environ.get("AGENT_ADDRESS", DEFAULT_ADDRESS)
        self.timeout = timeout  # a whole run, several model calls: minutes, not seconds
        stub = AgentStub(make_channel(self.address, options))
        self._run = bind(stub, SERVICE, "Run", interceptors)

    def run(self, messages: Iterable[Message]) -> Iterator[RunEvent]:
        """`Progress` events while the agent works, then one `Answer`. Closing the iterator early
        (the caller went away) cancels the run on the server."""
        response = self._run(RunRequest(messages=messages), self.timeout)
        try:
            yield from response
        finally:
            close(response)
