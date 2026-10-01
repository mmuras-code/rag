"""`python -m agent`: serve the agent.v1.Agent gRPC service on AGENT_PORT (default 8002)."""

import os

from common.log import setup_logging
from observability import setup_telemetry

from agent.server import serve

setup_logging("agent")  # logs/agent.<time>.log and stderr; see common/log.py

if __name__ == "__main__":
    setup_telemetry("agent")  # spans to Phoenix, metrics to Grafana; before the server is built
    serve(int(os.environ.get("AGENT_PORT", "8002")))
