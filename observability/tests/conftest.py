"""Metrics go to an in-memory reader in tests, never to Grafana."""

import pytest
from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

_reader = InMemoryMetricReader()
metrics.set_meter_provider(MeterProvider(metric_readers=[_reader]))


@pytest.fixture
def recorded():
    """`recorded()` -> {(operation, outcome, extra attrs...): count} since the test started."""
    def counts(before=_snapshot()):
        now = _snapshot()
        return {k: v - before.get(k, 0) for k, v in now.items() if v - before.get(k, 0)}
    yield counts


def _snapshot() -> dict:
    data = _reader.get_metrics_data()
    out = {}
    for rm in data.resource_metrics if data else []:
        for sm in rm.scope_metrics:
            for m in sm.metrics:
                if m.name == "ml.operations":
                    for p in m.data.data_points:
                        out[tuple(sorted(p.attributes.items()))] = p.value
    return out


@pytest.fixture
def timings():
    """`timings()` -> {(attrs...): (call count, total seconds)} of `ml.time` since the test started."""
    def calls(before=_histogram("ml.time")):
        now = _histogram("ml.time")
        out = {}
        for k, (count, total) in now.items():
            old_count, old_total = before.get(k, (0, 0.0))
            if count - old_count:
                out[k] = (count - old_count, total - old_total)
        return out
    yield calls


def _histogram(name: str) -> dict:
    data = _reader.get_metrics_data()
    out = {}
    for rm in data.resource_metrics if data else []:
        for sm in rm.scope_metrics:
            for m in sm.metrics:
                if m.name == name:
                    for p in m.data.data_points:
                        out[tuple(sorted(p.attributes.items()))] = (p.count, p.sum)
    return out
