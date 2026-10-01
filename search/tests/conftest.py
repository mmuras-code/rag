"""Telemetry is off in tests: nothing goes to Phoenix or Grafana."""

import os

os.environ["TRACING_ENABLED"] = "false"
os.environ["METRICS_ENABLED"] = "false"
