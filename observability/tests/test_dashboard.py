"""Smoke test of grafana/dashboard.py: build() runs and gives a JSON dashboard with panels."""

import importlib.util
import json
from pathlib import Path

DASHBOARD = Path(__file__).parents[1] / "grafana" / "dashboard.py"


def load_dashboard():
    spec = importlib.util.spec_from_file_location("dashboard", DASHBOARD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_gives_json_with_panels():
    dashboard = load_dashboard()
    model = json.loads(json.dumps(dashboard.build()))
    assert model["uid"] == dashboard.UID
    panels = [p for p in model["panels"] if p.get("type") != "row"]
    assert panels
    assert all(p.get("targets") for p in panels)
