import socket

import observability
from observability import instance_id, service_resource


def test_instance_is_the_argument_then_pod_name_then_hostname(monkeypatch):
    monkeypatch.setenv("POD_NAME", "agent-7f9c")
    assert instance_id("given") == "given"
    assert instance_id() == "agent-7f9c"
    monkeypatch.delenv("POD_NAME")
    assert instance_id() == socket.gethostname()


def test_resource_names_service_and_pod(monkeypatch):
    monkeypatch.setenv("POD_NAME", "agent-7f9c")
    attrs = service_resource("agent").attributes
    assert attrs["service.name"] == "agent"
    assert attrs["service.instance.id"] == "agent-7f9c"


def test_metrics_carry_service_and_pod(monkeypatch):
    monkeypatch.setattr(observability.metrics, "_meter_provider", None)
    monkeypatch.delenv("METRICS_ENABLED", raising=False)
    monkeypatch.setattr(observability.metrics.metrics, "set_meter_provider", lambda p: None)
    provider = observability.setup_metrics("agent", instance="agent-7f9c")
    try:
        attrs = provider._sdk_config.resource.attributes
        assert (attrs["service.name"], attrs["service.instance.id"]) == ("agent", "agent-7f9c")
    finally:
        provider.shutdown()
