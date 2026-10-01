"""Metrics: request count, latency and outcome of every operation, sent over OTLP to Grafana.

Every operation (an HTTP request, an agent run, a model call, a search) records exactly one
outcome:

- `success`
- `error`: the caller's mistake (bad input, unknown route, wrong key). Raise `UserError`, or
  answer 4xx. A `GeneratorExit` (a generator closed before it finished) counts here too.
- `fault`: a modelled service failure, one the code expects and names (a dependency is down or
  times out). Raise `ServiceFault` (or a subclass), or answer 5xx on purpose.
- `failure`: anything unplanned: every other exception.

Two instruments, shared by every service, with the operation and outcome as attributes:

- `ml.operations` (counter): one per operation. In Prometheus `ml_operations_total`.
- `ml.operation.duration` (histogram, seconds): its latency. In Prometheus
  `ml_operation_duration_seconds_{bucket,sum,count}`.

A caller that disconnects mid-stream is not tracked yet. Starlette's `StreamingResponse` absorbs
the disconnect and returns normally, so `OutcomeMiddleware` records the status already sent
(usually 200, so `success`); an `operation` inside the stream records whatever exception reaches
it, if any.

Call `setup_metrics(service)` once at process start (it also names the pod, see resource.py); until then (and with METRICS_ENABLED=false)
recording does nothing. Names and attributes are in ../../docs/telemetry.md.
"""

import inspect
import os
import time
from contextlib import ContextDecorator
from enum import StrEnum

from common.log import get_logger
from opentelemetry import metrics
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.metrics.view import ExplicitBucketHistogramAggregation, View
from opentelemetry.sdk.resources import SERVICE_INSTANCE_ID

from observability.resource import service_resource

log = get_logger("observability.metrics")

DEFAULT_METRICS_ENDPOINT = "http://localhost:4318"  # Grafana otel-lgtm, OTLP over HTTP
# Seconds. Wide on purpose: an HTTP check takes milliseconds, an agent run minutes.
DURATION_BUCKETS = [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300, 600]


class Outcome(StrEnum):
    SUCCESS = "success"
    ERROR = "error"
    FAULT = "fault"
    FAILURE = "failure"


class UserError(Exception):
    """The caller's mistake. Recorded as `error`."""


class ServiceFault(RuntimeError):
    """A failure the service expects and names, e.g. a dependency is down. Recorded as `fault`."""


def classify(exc: BaseException) -> Outcome:
    """The outcome for an exception. Looks through explicit causes (`raise ... from e`) and
    exception groups, because frameworks wrap the original (e.g. Starlette, once a streamed
    response started). Not through `__context__`: an exception raised while handling another
    (a bug in an `except ServiceFault:` block) is its own outcome."""
    seen, todo = set(), [exc]
    while todo:
        e = todo.pop()
        if e is None or id(e) in seen:
            continue
        seen.add(id(e))
        if isinstance(e, UserError | GeneratorExit):
            return Outcome.ERROR
        if isinstance(e, ServiceFault):
            return Outcome.FAULT
        todo += [e.__cause__, *getattr(e, "exceptions", ())]
    return Outcome.FAILURE


def outcome_for_status(status: int) -> Outcome:
    """HTTP status to outcome: 4xx is the caller's error, a 5xx answered on purpose is a fault."""
    if status < 400:
        return Outcome.SUCCESS
    return Outcome.ERROR if status < 500 else Outcome.FAULT


_meter = metrics.get_meter("observability")
_count = _meter.create_counter(
    "ml.operations", unit="{operation}", description="Operations, by operation and outcome")
_duration = _meter.create_histogram(
    "ml.operation.duration", unit="s", description="Operation latency, by operation and outcome",
    explicit_bucket_boundaries_advisory=DURATION_BUCKETS)


def record(name: str, outcome: Outcome, seconds: float, **attributes: str) -> None:
    attrs = {"operation": name, "outcome": outcome.value, **attributes}
    _count.add(1, attrs)
    _duration.record(seconds, attrs)


class operation(ContextDecorator):
    """Measures one operation: `with operation("llm.chat", model="anthropic/claude-haiku-4.5"):` or as a decorator.

    An exception decides the outcome (see `classify`) and is re-raised. Without one the outcome is
    `success`, unless `set_outcome` chose another (e.g. from an HTTP status) during this `with`.

    As a decorator it measures plain functions only: on an `async def` or a generator function it
    would measure creating the coroutine or generator, not running it, so it raises TypeError.
    Put a plain `with operation(...):` inside the function body instead (it works in `async def`).
    """

    def __init__(self, name: str, **attributes: str):
        self.name = name
        self.attributes = attributes
        self._outcome: Outcome | None = None
        self._start = 0.0

    def _recreate_cm(self):
        # A fresh instance per decorated call, so concurrent calls do not share the start time.
        return operation(self.name, **self.attributes)

    def __call__(self, func):
        if (inspect.iscoroutinefunction(func) or inspect.isgeneratorfunction(func)
                or inspect.isasyncgenfunction(func)):
            raise TypeError(f"@operation({self.name!r}) on {func.__qualname__}: it would measure "
                            "only creating the coroutine or generator. Put `with operation(...):` "
                            "inside the function body instead.")
        return super().__call__(func)

    def set_outcome(self, outcome: Outcome) -> None:
        self._outcome = outcome

    def __enter__(self):
        self._outcome = None  # an instance may be reused; set_outcome applies to one use
        self._start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb):
        outcome = classify(exc) if exc else (self._outcome or Outcome.SUCCESS)
        record(self.name, outcome, time.perf_counter() - self._start, **self.attributes)
        return False


class OutcomeMiddleware:
    """ASGI middleware: one `operation` per HTTP request, attributes `method` and `route` (the
    route template, `unmatched` for unknown paths). The outcome comes from the exception, else the
    status. It wraps the whole response, so a streamed body that fails midway counts too."""

    def __init__(self, app, name: str):
        self.app = app
        self.name = name

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        status = 500

        async def send_status(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        op = operation(self.name, method=scope["method"])
        with op:
            try:
                await self.app(scope, receive, send_status)
                op.set_outcome(outcome_for_status(status))
            finally:
                op.attributes["route"] = getattr(scope.get("route"), "path", "unmatched")


_meter_provider: MeterProvider | None = None


def setup_metrics(service: str, instance: str | None = None) -> MeterProvider | None:
    """Export metrics once per process to METRICS_COLLECTOR_ENDPOINT (default
    http://localhost:4318), as `service.name` = `service` and `service.instance.id` = the pod
    (see resource.py). Returns the provider, or None if METRICS_ENABLED=false."""
    global _meter_provider
    if _meter_provider is not None:
        return _meter_provider
    if os.environ.get("METRICS_ENABLED", "true").lower() == "false":
        log.info("metrics disabled (METRICS_ENABLED=false)")
        return None
    endpoint = os.environ.get("METRICS_COLLECTOR_ENDPOINT", DEFAULT_METRICS_ENDPOINT).rstrip("/")
    reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=f"{endpoint}/v1/metrics"),
        export_interval_millis=int(os.environ.get("METRICS_EXPORT_INTERVAL_MS", "10000")),
    )
    # FastAPI's own request-duration histogram stops at 10 s; agent requests run longer.
    wide = View(instrument_name="http.server.request.duration",
                aggregation=ExplicitBucketHistogramAggregation(DURATION_BUCKETS))
    resource = service_resource(service, instance)
    _meter_provider = MeterProvider(resource=resource, metric_readers=[reader], views=[wide])
    metrics.set_meter_provider(_meter_provider)
    log.info("metrics to %s as %s on %s", endpoint, service, resource.attributes[SERVICE_INSTANCE_ID])
    return _meter_provider
