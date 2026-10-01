import observability


def test_disabled_returns_none(monkeypatch):
    monkeypatch.setattr(observability, "_provider", None)
    monkeypatch.setenv("TRACING_ENABLED", "false")
    assert observability.setup_tracing() is None


def test_registers_once_with_endpoint_and_project(monkeypatch):
    calls = []
    monkeypatch.setattr(observability, "_provider", None)
    monkeypatch.delenv("TRACING_ENABLED", raising=False)
    monkeypatch.setenv("PHOENIX_COLLECTOR_ENDPOINT", "http://phoenix:6006/")
    monkeypatch.delenv("PHOENIX_PROJECT_NAME", raising=False)
    monkeypatch.setattr(observability, "register", lambda **kw: calls.append(kw) or "provider")
    monkeypatch.setattr(observability.LangChainInstrumentor, "instrument", lambda self, **kw: None)
    assert observability.setup_tracing() == "provider"
    assert observability.setup_tracing() == "provider"
    assert len(calls) == 1
    assert calls[0]["endpoint"] == "http://phoenix:6006/v1/traces"
    assert calls[0]["project_name"] == "ml"


def test_spans_carry_service_and_pod(monkeypatch):
    calls = []
    monkeypatch.setattr(observability, "_provider", None)
    monkeypatch.delenv("TRACING_ENABLED", raising=False)
    monkeypatch.setattr(observability, "register", lambda **kw: calls.append(kw) or "provider")
    monkeypatch.setattr(observability.LangChainInstrumentor, "instrument", lambda self, **kw: None)
    observability.setup_tracing("agent", instance="agent-7f9c")
    attrs = calls[0]["resource"].attributes
    assert (attrs["service.name"], attrs["service.instance.id"]) == ("agent", "agent-7f9c")
