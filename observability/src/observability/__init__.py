"""Telemetry helper every service imports: traces to Phoenix, metrics to Grafana.

A service calls `setup_telemetry(name)` once at process start: tracing, metrics, httpx
instrumentation (outgoing HTTP calls become spans and carry the trace on) and gRPC server
instrumentation (a gRPC server built afterwards makes a span per call and continues the caller's
trace; the generated clients' wrappers in proto/ send it in the call's metadata). An HTTP service also calls
`instrument_app(app, name)`. Metrics (request count, latency, error/fault/failure) are in
`metrics.py`, the run time of any function (`@timed`) in `timing.py`; the whole system is
described in ../../docs/telemetry.md.

`setup_tracing()` once at process start (calling it again does nothing). It registers a
global tracer provider that exports to PHOENIX_COLLECTOR_ENDPOINT (default http://localhost:6006,
the Phoenix server from compose.yaml), into the Phoenix project PHOENIX_PROJECT_NAME (default
`ml`, one project for every service so a request is one trace), and instruments LangChain, which
covers LangGraph graphs. Set TRACING_ENABLED=false to turn it off. Span attribute names are in
../docs/telemetry.md.
"""

import os

from common.log import get_logger
from openinference.instrumentation.langchain import LangChainInstrumentor
from opentelemetry import trace
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from phoenix.otel import register

from observability.metrics import (
    Outcome,
    OutcomeMiddleware,
    ServiceFault,
    UserError,
    operation,
    setup_metrics,
)
from observability.resource import instance_id, service_resource
from observability.timing import timed

log = get_logger("observability")

DEFAULT_ENDPOINT = "http://localhost:6006"
DEFAULT_PROJECT = "ml"

_provider = None


def setup_tracing(service: str | None = None, instance: str | None = None) -> trace.TracerProvider | None:
    """Register tracing to Phoenix once per process. Returns the provider, or None if disabled.
    With `service`, spans carry `service.name` and `service.instance.id` (the pod, see
    resource.py)."""
    global _provider
    if _provider is not None:
        return _provider
    if os.environ.get("TRACING_ENABLED", "true").lower() == "false":
        log.info("tracing disabled (TRACING_ENABLED=false)")
        return None
    endpoint = os.environ.get("PHOENIX_COLLECTOR_ENDPOINT", DEFAULT_ENDPOINT).rstrip("/")
    resource = {"resource": service_resource(service, instance)} if service else {}
    _provider = register(
        endpoint=f"{endpoint}/v1/traces",
        protocol="http/protobuf",
        project_name=os.environ.get("PHOENIX_PROJECT_NAME", DEFAULT_PROJECT),
        batch=True,
        verbose=False,
        **resource,
    )
    LangChainInstrumentor().instrument(tracer_provider=_provider)
    log.info("tracing to %s", endpoint)
    return _provider


def tracer(name: str) -> trace.Tracer:
    """A tracer for manual spans. Before setup_tracing, or with tracing off, spans are no-ops."""
    return trace.get_tracer(name)


def setup_telemetry(service: str, instance: str | None = None) -> None:
    """Tracing, metrics and httpx instrumentation, once per process. The first caller names the
    process: `service.name` = `service` and `service.instance.id` = `instance`, else POD_NAME,
    else the hostname (see resource.py). Every metric and span carries both; in Prometheus they
    are the `job` and `instance` labels."""
    # Stable HTTP semantic conventions: `http.server.request.duration` in seconds, not the old
    # `http.server.duration` in milliseconds. Read once, when the first instrumentor starts.
    os.environ.setdefault("OTEL_SEMCONV_STABILITY_OPT_IN", "http")
    setup_tracing(service, instance)
    setup_metrics(service, instance)
    if not HTTPXClientInstrumentor().is_instrumented_by_opentelemetry:
        HTTPXClientInstrumentor().instrument()
    _instrument_grpc()


def _instrument_grpc() -> None:
    """A span per gRPC call on servers created after this, continuing the trace from the call's
    metadata. A no-op where grpcio is not installed.

    The client side is not instrumented: it wraps a streaming call in a generator that attaches
    the span's context, and Starlette steps a streamed response from changing contexts, so the
    detach fails. The wrappers in proto/ send `traceparent` themselves instead."""
    try:
        from opentelemetry.instrumentation.grpc import GrpcInstrumentorServer
    except ImportError:
        return
    if not GrpcInstrumentorServer().is_instrumented_by_opentelemetry:
        GrpcInstrumentorServer().instrument()


def instrument_app(app, name: str) -> None:
    """For a FastAPI app: a span per request (to Phoenix) and the `name` operation metrics per
    request (see `OutcomeMiddleware`). Call before the app starts."""
    # Imported here: it needs fastapi, which services without an HTTP server (llm/) do not have.
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    app.add_middleware(OutcomeMiddleware, name=name)
    FastAPIInstrumentor.instrument_app(app)


__all__ = [
    "Outcome",
    "OutcomeMiddleware",
    "ServiceFault",
    "UserError",
    "instance_id",
    "instrument_app",
    "operation",
    "service_resource",
    "setup_metrics",
    "setup_telemetry",
    "setup_tracing",
    "timed",
    "tracer",
]
