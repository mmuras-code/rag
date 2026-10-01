"""Spans go to an in-memory exporter in tests, never to Phoenix; metrics are off."""

import os

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

os.environ["TRACING_ENABLED"] = "false"
os.environ["METRICS_ENABLED"] = "false"
os.environ.setdefault("OR_KEY", "test")  # default clients are built, never called

_exporter = InMemorySpanExporter()
_provider = TracerProvider()
_provider.add_span_processor(SimpleSpanProcessor(_exporter))
trace.set_tracer_provider(_provider)


@pytest.fixture
def spans():
    _exporter.clear()
    yield _exporter
    _exporter.clear()
