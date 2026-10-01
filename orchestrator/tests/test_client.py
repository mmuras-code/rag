from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from orchestrator.app import app
from orchestrator.backends import backend
from orchestrator.client import OrchestratorClient


@pytest.fixture
def client():
    llm = MagicMock(spec=["chat"])
    llm.chat.return_value = "paris"
    app.dependency_overrides[backend] = lambda: llm
    yield OrchestratorClient(http=TestClient(app)), llm
    app.dependency_overrides.clear()


def test_models(client):
    assert client[0].models() == ["personal-rag-v0.1"]


def test_ask_sends_one_user_message(client):
    c, llm = client
    assert c.ask("capital of france?") == "paris"
    llm.chat.assert_called_once_with([{"role": "user", "content": "capital of france?"}])


def test_unknown_route_raises(client):
    # TestClient is built on httpx2, so the error class differs from the real httpx one.
    with pytest.raises(Exception, match="404"):
        client[0].ask("hi", model="nope")


def test_url_and_key_from_env(monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_URL", "http://orch:9000/")
    monkeypatch.setenv("ORCHESTRATOR_API_KEY", "k")
    c = OrchestratorClient()
    assert str(c.http.base_url) == "http://orch:9000"
    assert c.http.headers["Authorization"] == "Bearer k"


def test_reply_carries_the_trace_id(client, spans):
    reply = client[0].reply([{"role": "user", "content": "hi"}])
    assert reply.text == "paris"
    server = [s for s in spans.get_finished_spans() if s.kind.name == "SERVER"]
    assert reply.trace_id == f"{server[0].context.trace_id:032x}"
