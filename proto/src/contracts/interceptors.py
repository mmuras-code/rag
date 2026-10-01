"""The request/response interface every client wrapper calls through, and interceptors built on it.

A wrapper (`<service>/client.py`) sends each call as a `Request` through a chain of
`Interceptor`s, ending at the generated stub. An interceptor sees the request, may change it
(`request.replace(...)`), calls `proceed(request)` (zero, one or several times) and returns the
`Response`, or raises. The chain is built once, in the wrapper's constructor:

    SearchClient(interceptors=[Retry(max_attempts=3), LogCalls()])

The order is outermost first, after `TraceContext`, which every wrapper puts first. A unary call's
response is the generated response message; a server-streaming call's (`request.streaming`) is an
iterator of them, which raises `grpc.RpcError` while iterating. Errors are the stub's
`grpc.RpcError`.

    class LogCalls:
        def intercept(self, request: Request, proceed: Handler) -> Response:
            log.info("calling %s", request.method)
            return proceed(request)

The interface knows nothing about gRPC's own interceptor API, so interceptors keep working if the
transport changes (ADR 0005).
"""

import dataclasses
import random
import time
from collections.abc import Callable, Iterable, Iterator, Sequence
from typing import Any, Protocol

import grpc
from google.protobuf.descriptor import ServiceDescriptor
from google.protobuf.message import Message
from opentelemetry import propagate

# Channel options every wrapper starts from (a caller's `options` override them). After a failed
# connection gRPC waits before reconnecting, 1 s at first and up to 120 s by default, and calls
# in that window fail at once. Short waits let `Retry` reach a server that has just restarted.
DEFAULT_CHANNEL_OPTIONS = (
    ("grpc.initial_reconnect_backoff_ms", 100),
    ("grpc.min_reconnect_backoff_ms", 100),
    ("grpc.max_reconnect_backoff_ms", 1000),
)

Response = Any  # unary: the response message; server streaming: an iterator of response messages


@dataclasses.dataclass(frozen=True)
class Request:
    method: str  # the full RPC name, e.g. "/search.v1.Search/Query"
    message: Message  # the generated request message
    timeout: float | None = None  # seconds, for one attempt
    metadata: tuple[tuple[str, str], ...] = ()
    streaming: bool = False  # the response is a stream of messages

    def replace(self, **changes) -> "Request":
        return dataclasses.replace(self, **changes)


Handler = Callable[[Request], Response]


class Interceptor(Protocol):
    def intercept(self, request: Request, proceed: Handler) -> Response: ...


def chain(interceptors: Sequence[Interceptor], terminal: Handler) -> Handler:
    """One handler that runs `interceptors` in order, outermost first, then `terminal`."""
    handler = terminal
    for interceptor in reversed(interceptors):
        handler = (lambda i, nxt: lambda request: i.intercept(request, nxt))(interceptor, handler)
    return handler


def make_channel(address: str, options=()) -> grpc.Channel:
    """An insecure channel to `address` with `DEFAULT_CHANNEL_OPTIONS` overridden by `options`.
    It connects on first use and reconnects by itself after the server restarts."""
    return grpc.insecure_channel(address, options=list({**dict(DEFAULT_CHANNEL_OPTIONS), **dict(options)}.items()))


def bind(stub, service: ServiceDescriptor, name: str, interceptors: Sequence[Interceptor]) -> Callable:
    """`call(message, timeout)` for one RPC of a generated stub, through `TraceContext` and then
    `interceptors`. The method name and whether it streams come from the `.proto` descriptor."""
    method = service.methods_by_name[name]
    stub_method = getattr(stub, name)

    def terminal(request: Request) -> Response:
        return stub_method(request.message, timeout=request.timeout, metadata=list(request.metadata))

    handler = chain([TraceContext(), *interceptors], terminal)
    full_name = f"/{service.full_name}/{name}"
    return lambda message, timeout=None: handler(
        Request(full_name, message, timeout, streaming=method.server_streaming))


def close(response: Response) -> None:
    """Stop a streaming response early: cancel the gRPC call, or close the generator wrapping it.
    A no-op once the stream has ended."""
    if hasattr(response, "cancel"):
        response.cancel()
    elif hasattr(response, "close"):
        response.close()


class TraceContext:
    """Adds the current trace context (`traceparent`) to the metadata, where the server's gRPC
    instrumentation (observability's `setup_telemetry`) continues the trace. Adds nothing when
    there is no trace. Every wrapper puts it first."""

    def intercept(self, request: Request, proceed: Handler) -> Response:
        carrier: dict[str, str] = {}
        propagate.inject(carrier)
        return proceed(request.replace(metadata=(*request.metadata, *carrier.items())))


class Retry:
    """Retries a call that failed with one of `codes` (default: UNAVAILABLE, the server down or
    restarting), up to `max_attempts` in all, with exponential backoff and jitter between them.

    A streaming call is retried only until its first message arrives; after that its errors pass
    through, since the server has already done work. Retry only calls that are safe to repeat:
    each attempt of the agent's `Run` pays for its model calls again.
    """

    def __init__(self, max_attempts: int = 3, codes: Iterable[grpc.StatusCode] = (grpc.StatusCode.UNAVAILABLE,),
                 initial_backoff: float = 0.2, max_backoff: float = 2.0, sleep: Callable[[float], None] = time.sleep):
        self.max_attempts, self.codes = max_attempts, frozenset(codes)
        self.initial_backoff, self.max_backoff, self.sleep = initial_backoff, max_backoff, sleep

    def _wait(self, attempt: int) -> None:
        backoff = min(self.max_backoff, self.initial_backoff * 2 ** (attempt - 1))
        self.sleep(backoff * random.uniform(0.5, 1))

    def _retryable(self, error: grpc.RpcError, attempt: int) -> bool:
        return attempt < self.max_attempts and error.code() in self.codes

    def intercept(self, request: Request, proceed: Handler) -> Response:
        if request.streaming:
            return self._stream(request, proceed)
        for attempt in range(1, self.max_attempts + 1):
            try:
                return proceed(request)
            except grpc.RpcError as e:
                if not self._retryable(e, attempt):
                    raise
                self._wait(attempt)

    def _stream(self, request: Request, proceed: Handler) -> Iterator:
        for attempt in range(1, self.max_attempts + 1):
            response = proceed(request)
            stream = iter(response)
            try:
                first = next(stream)
            except StopIteration:
                return
            except grpc.RpcError as e:
                if not self._retryable(e, attempt):
                    raise
                self._wait(attempt)
                continue
            try:
                yield first
                yield from stream
            finally:
                close(response)
            return
