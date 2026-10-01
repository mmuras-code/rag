import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.testclient import TestClient

import observability
from observability.metrics import (
    Outcome,
    OutcomeMiddleware,
    ServiceFault,
    UserError,
    classify,
    operation,
    outcome_for_status,
)


def key(op, outcome, **extra):
    return tuple(sorted({"operation": op, "outcome": outcome, **extra}.items()))


@pytest.mark.parametrize("exc, outcome", [
    (UserError("bad"), Outcome.ERROR),
    (ServiceFault("down"), Outcome.FAULT),
    (ValueError("bug"), Outcome.FAILURE),
    (GeneratorExit(), Outcome.ERROR),
])
def test_classify(exc, outcome):
    assert classify(exc) is outcome


def test_classify_looks_through_causes_and_groups():
    try:
        try:
            raise ServiceFault("down")
        except ServiceFault as e:
            raise RuntimeError("response already started") from e
    except RuntimeError as wrapped:
        assert classify(wrapped) is Outcome.FAULT
    assert classify(ExceptionGroup("g", [ServiceFault("down")])) is Outcome.FAULT


def test_classify_ignores_exception_context():
    # A bug while handling a fault is a failure, not the fault it was handling.
    try:
        try:
            raise ServiceFault("down")
        except ServiceFault:
            {}["missing"]
    except KeyError as bug:
        assert bug.__context__ is not None
        assert classify(bug) is Outcome.FAILURE


@pytest.mark.parametrize("status, outcome", [
    (200, Outcome.SUCCESS), (404, Outcome.ERROR), (503, Outcome.FAULT), (500, Outcome.FAULT),
])
def test_outcome_for_status(status, outcome):
    assert outcome_for_status(status) is outcome


def test_operation_records_success_and_reraises(recorded):
    with operation("t.ok", model="m"):
        pass
    with pytest.raises(ServiceFault), operation("t.ok", model="m"):
        raise ServiceFault("down")
    assert recorded() == {key("t.ok", "success", model="m"): 1, key("t.ok", "fault", model="m"): 1}


def test_operation_as_decorator(recorded):
    @operation("t.deco")
    def f(fail):
        if fail:
            raise ValueError("bug")

    f(False)
    with pytest.raises(ValueError):
        f(True)
    assert recorded() == {key("t.deco", "success"): 1, key("t.deco", "failure"): 1}


async def _coroutine():
    pass


def _generator():
    yield


async def _async_generator():
    yield


@pytest.mark.parametrize("func", [_coroutine, _generator, _async_generator])
def test_operation_decorator_rejects_coroutines_and_generators(func):
    with pytest.raises(TypeError, match="inside the function body"):
        operation("t.deco")(func)


def test_reused_operation_resets_outcome(recorded):
    op = operation("t.reuse")
    with op:
        op.set_outcome(Outcome.ERROR)
    with op:
        pass
    assert recorded() == {key("t.reuse", "error"): 1, key("t.reuse", "success"): 1}


def test_nested_operations_record_their_own_outcome(recorded):
    with pytest.raises(ServiceFault), operation("t.outer") as outer:
        outer.set_outcome(Outcome.ERROR)
        with operation("t.inner") as inner:
            inner.set_outcome(Outcome.FAULT)
        with operation("t.inner"):
            pass
        raise ServiceFault("down")
    assert recorded() == {key("t.inner", "fault"): 1, key("t.inner", "success"): 1,
                          key("t.outer", "fault"): 1}


def make_app():
    app = FastAPI()
    app.add_middleware(OutcomeMiddleware, name="t.http")

    @app.exception_handler(ServiceFault)
    def fault(request, exc):
        return JSONResponse(status_code=503, content={})

    @app.get("/ok")
    def ok():
        return {}

    @app.get("/missing")
    def missing():
        raise HTTPException(404)

    @app.get("/fault")
    def fault_route():
        raise ServiceFault("down")

    @app.get("/bug")
    def bug():
        raise ValueError("bug")

    @app.get("/stream-fault")
    def stream_fault():
        def body():
            yield "partial"
            raise ServiceFault("down midway")
        return StreamingResponse(body())

    return app


def test_middleware_classifies_requests(recorded):
    client = TestClient(make_app(), raise_server_exceptions=False)
    assert client.get("/ok").status_code == 200
    assert client.get("/missing").status_code == 404
    assert client.get("/nowhere").status_code == 404
    assert client.get("/fault").status_code == 503
    assert client.get("/bug").status_code == 500
    with pytest.raises(Exception):
        TestClient(make_app()).get("/stream-fault")
    got = recorded()
    assert got == {
        key("t.http", "success", method="GET", route="/ok"): 1,
        key("t.http", "error", method="GET", route="/missing"): 1,
        key("t.http", "error", method="GET", route="unmatched"): 1,
        key("t.http", "fault", method="GET", route="/fault"): 1,
        key("t.http", "failure", method="GET", route="/bug"): 1,
        key("t.http", "fault", method="GET", route="/stream-fault"): 1,
    }


def test_setup_metrics_disabled(monkeypatch):
    monkeypatch.setattr(observability.metrics, "_meter_provider", None)
    monkeypatch.setenv("METRICS_ENABLED", "false")
    assert observability.setup_metrics("svc") is None


def test_setup_metrics_once_with_endpoint(monkeypatch):
    providers = []
    monkeypatch.setattr(observability.metrics, "_meter_provider", None)
    monkeypatch.delenv("METRICS_ENABLED", raising=False)
    monkeypatch.setenv("METRICS_COLLECTOR_ENDPOINT", "http://lgtm:4318/")
    monkeypatch.setattr(observability.metrics.metrics, "set_meter_provider", providers.append)
    endpoints = []
    real_exporter = observability.metrics.OTLPMetricExporter
    monkeypatch.setattr(observability.metrics, "OTLPMetricExporter",
                        lambda endpoint: endpoints.append(endpoint) or real_exporter(endpoint=endpoint))
    first = observability.setup_metrics("svc")
    assert observability.setup_metrics("other") is first
    assert providers == [first]
    assert endpoints == ["http://lgtm:4318/v1/metrics"]
    first.shutdown()
