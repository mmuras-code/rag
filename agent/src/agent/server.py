"""The agent as the `agent.v1.Agent` gRPC service (contract: ../../../proto, contracts.agent.v1).

`Run` runs the graph (graph.py) in a background thread and streams a `Progress` event every
`tick_seconds` while it works, then the `Answer`, so the caller can show the user it is alive.

Errors become gRPC status codes, which the caller's generated client raises as `grpc.RpcError`:
a `ServiceFault` (search or OpenRouter down) is UNAVAILABLE, a `UserError` or a malformed request
INVALID_ARGUMENT, anything else INTERNAL.
"""

import contextvars
import queue
import threading
from collections.abc import Iterator
from concurrent import futures

import grpc
from common.log import get_logger
from contracts.agent.v1 import agent_pb2, agent_pb2_grpc
from observability import ServiceFault, UserError

from agent.graph import build_graph, run

log = get_logger("agent.server")

ROLES = {agent_pb2.ROLE_SYSTEM: "system", agent_pb2.ROLE_USER: "user", agent_pb2.ROLE_ASSISTANT: "assistant"}


class AgentService(agent_pb2_grpc.AgentServicer):
    def __init__(self, graph=None, tick_seconds: float = 3):
        self.graph = graph or build_graph()
        self.tick_seconds = tick_seconds

    def Run(self, request: agent_pb2.RunRequest, context) -> Iterator[agent_pb2.RunEvent]:
        if not request.messages:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "messages must not be empty")
        if any(m.role not in ROLES for m in request.messages):
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "every message needs a role")
        messages = [{"role": ROLES[m.role], "content": m.content} for m in request.messages]
        done: queue.Queue = queue.Queue(maxsize=1)

        def work():
            try:
                done.put((True, run(messages, self.graph)))
            except Exception as e:  # reported from the streaming thread
                done.put((False, e))

        # Run in a copy of this context, so the agent span joins the caller's trace.
        threading.Thread(target=contextvars.copy_context().run, args=(work,), daemon=True).start()
        tick = 0
        while True:
            try:
                ok, value = done.get(timeout=self.tick_seconds)
            except queue.Empty:
                tick += 1
                yield agent_pb2.RunEvent(progress=agent_pb2.Progress(tick=tick))
                continue
            if ok:
                yield agent_pb2.RunEvent(answer=agent_pb2.Answer(text=value))
                return
            if isinstance(value, ServiceFault):
                context.abort(grpc.StatusCode.UNAVAILABLE, str(value))
            if isinstance(value, UserError):
                context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(value))
            log.error("run failed", exc_info=value)
            context.abort(grpc.StatusCode.INTERNAL, f"{type(value).__name__}: {value}")


def serve(port: int) -> None:
    """Serve until the process is stopped. Each call holds a worker thread for its whole run."""
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    agent_pb2_grpc.add_AgentServicer_to_server(AgentService(), server)
    server.add_insecure_port(f"127.0.0.1:{port}")
    server.start()
    log.info("serving agent.v1.Agent on 127.0.0.1:%d", port)
    server.wait_for_termination()
