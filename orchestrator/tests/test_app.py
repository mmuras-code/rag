import json
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from orchestrator import backends as backends_module
from orchestrator.app import app
from orchestrator.backends import BackendName, backend
from orchestrator.clients.stub_client import REPLY, StubClient
from orchestrator.schemas import ROUTE

client = TestClient(app)


@pytest.fixture
def fake():
    llm = MagicMock(spec=["chat"])
    llm.chat.return_value = "hello"
    app.dependency_overrides[backend] = lambda: llm
    yield llm
    app.dependency_overrides.clear()


def post(model=ROUTE, stream=False):
    return client.post(
        "/v1/chat/completions",
        json={"model": model, "stream": stream, "messages": [{"role": "user", "content": "hi"}]},
    )


def test_models_lists_one_route():
    assert [m["id"] for m in client.get("/v1/models").json()["data"]] == ["personal-rag-v0.1"]


def test_chat_uses_injected_backend(fake):
    assert post().json()["choices"][0]["message"]["content"] == "hello"
    fake.chat.assert_called_once_with([{"role": "user", "content": "hi"}])


def test_stream_ends_with_done(fake):
    r = post(stream=True)
    assert '"content": "hello"' in r.text
    assert '"finish_reason": "stop"' in r.text
    assert r.text.rstrip().endswith("data: [DONE]")


def test_unknown_route(fake):
    assert post("stub").status_code == 404


@pytest.fixture
def fresh_backend():
    backend.cache_clear()
    yield
    backend.cache_clear()


def test_backend_from_env_stub(monkeypatch, fresh_backend):
    monkeypatch.setenv("ORCHESTRATOR_BACKEND", "stub")
    assert isinstance(backend(), StubClient)
    assert post().json()["choices"][0]["message"]["content"] == REPLY


def test_backend_defaults_to_agent(monkeypatch, fresh_backend):
    monkeypatch.delenv("ORCHESTRATOR_BACKEND", raising=False)
    monkeypatch.setattr(
        backends_module, "BACKENDS", {BackendName.AGENT: lambda: "built agent", BackendName.STUB: StubClient}
    )
    assert backend() == "built agent"


def test_unknown_backend_fails(monkeypatch, fresh_backend):
    monkeypatch.setenv("ORCHESTRATOR_BACKEND", "nope")
    with pytest.raises(RuntimeError, match="ORCHESTRATOR_BACKEND"):
        backend()


def test_only_agent_and_stub_backends():
    assert [b.value for b in BackendName] == ["agent", "stub"]


def test_streaming_backend_sends_one_chunk_per_piece():
    llm = MagicMock(spec=["chat", "stream"])
    llm.stream.return_value = iter(["a", "b", "c"])
    app.dependency_overrides[backend] = lambda: llm
    try:
        contents = [l for l in post(stream=True).text.splitlines() if '"content": "' in l]
        assert len(contents) == 3
    finally:
        app.dependency_overrides.clear()


def test_service_fault_answers_503(fake):
    from observability import ServiceFault

    fake.chat.side_effect = ServiceFault("search is down")
    r = post()
    assert r.status_code == 503
    assert r.json()["error"] == {"message": "search is down", "type": "service_unavailable",
                                 "code": "ServiceFault"}


def test_healthz_needs_no_key(monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_API_KEY", "secret")
    assert client.get("/v1/models").status_code == 401
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_api_key_checked(monkeypatch, fake):
    monkeypatch.setenv("ORCHESTRATOR_API_KEY", "secret")
    assert client.get("/v1/models", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/v1/models", headers={"Authorization": "Bearer secret"}).status_code == 200


def failing_stream(exc):
    def stream(messages):
        yield "partial"
        raise exc

    llm = MagicMock(spec=["chat", "stream"])
    llm.stream.side_effect = stream
    return llm


def test_stream_failure_sends_error_then_done():
    from observability import ServiceFault

    app.dependency_overrides[backend] = lambda: failing_stream(ServiceFault("search is down"))
    try:
        # The exception is raised after the response is complete, for telemetry; the body is whole.
        r = TestClient(app, raise_server_exceptions=False).post(
            "/v1/chat/completions",
            json={"model": ROUTE, "stream": True, "messages": [{"role": "user", "content": "hi"}]})
    finally:
        app.dependency_overrides.clear()
    events = [l.removeprefix("data: ") for l in r.text.splitlines() if l]
    assert events[-1] == "[DONE]"
    assert json.loads(events[-2]) == {"error": {"message": "search is down", "type": "service_unavailable",
                                                "code": "ServiceFault"}}
    assert '"content": "partial"' in r.text
    assert '"finish_reason": "stop"' not in r.text


def test_stream_failure_is_raised_for_telemetry():
    app.dependency_overrides[backend] = lambda: failing_stream(ValueError("secret detail"))
    try:
        with pytest.raises(ValueError):
            post(stream=True)
    finally:
        app.dependency_overrides.clear()
