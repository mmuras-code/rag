"""Minimal OpenAI-compatible server for Open WebUI.

One route, `personal-rag-v0.1` (`ROUTE`), answered by the backend from `backends.py`. The rest is split out:
`schemas.py` (request bodies), `responses.py` (response bodies and SSE chunks), `auth.py` (API key).
Model clients live in agent/, not here.

Telemetry (observability/): a span per request to Phoenix, and per request the
`orchestrator.http` operation metrics (count, latency, outcome) to Grafana. A `ServiceFault` from
the backend is a modelled failure: answered 503 and counted as a fault; anything else unhandled
is a failure, also when it happens midway through a stream (see `EventStream`). See
../../docs/telemetry.md.
"""

import uuid

from common.log import setup_logging
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from observability import ServiceFault, instrument_app, setup_telemetry
from opentelemetry import trace

from orchestrator.auth import check_key
from orchestrator.backends import Backend, answer, backend, pieces
from orchestrator.responses import EventStream, completion, error
from orchestrator.schemas import ROUTE, ChatRequest

setup_telemetry("orchestrator")
app = FastAPI(title="orchestrator")
instrument_app(app, "orchestrator.http")


@app.exception_handler(ServiceFault)
def service_fault(request: Request, exc: ServiceFault) -> JSONResponse:
    """A dependency failed in a known way: 503 in OpenAI's error shape, so Open WebUI shows it."""
    return JSONResponse(status_code=503, content=error(exc))


@app.get("/healthz")
def healthz():
    """Liveness only: no key needed and no dependency checked, so `just up` can wait on it."""
    return {"status": "ok"}


@app.get("/v1/models", dependencies=[Depends(check_key)])
def models():
    return {
        "object": "list",
        "data": [{"id": ROUTE, "object": "model", "created": 0, "owned_by": "ml"}],
    }


def request_id() -> str:
    """`chatcmpl-<trace id>`: the response names its trace in Phoenix, so callers (eval/) can read
    the request's tokens and cost back. A random id when tracing is off."""
    ctx = trace.get_current_span().get_span_context()
    return f"chatcmpl-{trace.format_trace_id(ctx.trace_id) if ctx.is_valid else uuid.uuid4().hex}"


@app.post("/v1/chat/completions", dependencies=[Depends(check_key)])
def chat_completions(req: ChatRequest, llm: Backend = Depends(backend)):
    if req.model != ROUTE:
        raise HTTPException(status_code=404, detail=f"unknown route {req.model!r}")
    rid = request_id()
    messages = [m.model_dump() for m in req.messages]

    if not req.stream:
        return completion(rid, req.model, answer(llm, messages))

    return EventStream(rid, req.model, pieces(llm, messages))
