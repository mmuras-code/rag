"""What answers the route (`personal-rag-v0.1`): the agent service (agent/, over gRPC through the
client generated from proto/), or a stub that calls nothing.

Those are the only two, listed in `BackendName`. ORCHESTRATOR_BACKEND picks one (`agent` by
default). `backend` is a FastAPI dependency, so tests override it. The time the backend takes is
`ml.time` with `function` = `orchestrator.answer` or `orchestrator.stream` (`@timed`).
"""

import os
from collections.abc import Iterator
from enum import Enum
from functools import cache
from typing import Protocol

from observability import timed

from orchestrator.clients.agent_client import AgentBackend
from orchestrator.clients.stub_client import StubClient


class Backend(Protocol):
    """Answers a conversation. May also have `stream(messages) -> Iterator[str]`; backends
    without it are streamed as one chunk."""

    def chat(self, messages: list[dict]) -> str: ...


class BackendName(str, Enum):
    """The only backends: the agent, or the stub for testing the wiring without a model."""

    AGENT = "agent"
    STUB = "stub"


BACKENDS = {BackendName.AGENT: AgentBackend, BackendName.STUB: StubClient}


@cache
def backend() -> Backend:
    """The configured backend, built once. Unknown values fail at the first request."""
    value = os.environ.get("ORCHESTRATOR_BACKEND", BackendName.AGENT.value)
    try:
        name = BackendName(value)
    except ValueError:
        expected = [b.value for b in BackendName]
        raise RuntimeError(f"ORCHESTRATOR_BACKEND={value!r}; expected one of {expected}") from None
    return BACKENDS[name]()


@timed("orchestrator.answer")
def answer(llm: Backend, messages: list[dict]) -> str:
    """The whole answer, for a request that does not stream."""
    return llm.chat(messages)


@timed("orchestrator.stream")
def pieces(llm: Backend, messages: list[dict]) -> Iterator[str]:
    """The answer as stream pieces: the backend's own stream, or the whole answer as one piece.
    Timed until the last piece is sent (or the stream fails)."""
    if hasattr(llm, "stream"):
        yield from llm.stream(messages)
    else:
        yield llm.chat(messages)
