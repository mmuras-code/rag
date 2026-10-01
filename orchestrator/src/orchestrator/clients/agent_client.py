"""The agent backend: the agent service (../../../agent), called through the gRPC client generated
from its contract (contracts.agent.AgentClient, ../../../proto).

It converts Open WebUI's messages to the contract's, and the run's events back to stream pieces:
a counter line per `Progress` event (`1`, `2`, `3`, ... one every 3 seconds), then the answer, so
the user sees the agent is alive. An agent that is down or times out, or that reports a dependency
down (UNAVAILABLE), is a modelled failure (`AgentUnavailable`); any other gRPC error is raised as is.
"""

from collections.abc import Iterator

import grpc
from contracts.agent import AgentClient
from contracts.agent.v1.agent_pb2 import ROLE_ASSISTANT, ROLE_SYSTEM, ROLE_USER, Message
from observability import ServiceFault

ROLES = {"system": ROLE_SYSTEM, "developer": ROLE_SYSTEM, "user": ROLE_USER, "assistant": ROLE_ASSISTANT}
DOWN = {grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED}


class AgentUnavailable(ServiceFault):
    """The agent service could not be reached, timed out, or reported a dependency down."""


def text(content: str | list) -> str:
    """OpenAI content as plain text: multi-part content keeps only its text parts."""
    if isinstance(content, str):
        return content
    return "\n".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")


def to_messages(messages: list[dict]) -> list[Message]:
    """The contract's messages. Roles the agent has no use for (e.g. `tool`) are left out."""
    return [Message(role=ROLES[m["role"]], content=text(m.get("content", ""))) for m in messages
            if m["role"] in ROLES]


class AgentBackend:
    def __init__(self, client: AgentClient | None = None):
        self.client = client or AgentClient()

    def chat(self, messages: list[dict]) -> str:
        return next(e.answer.text for e in self._events(messages) if e.HasField("answer"))

    def stream(self, messages: list[dict]) -> Iterator[str]:
        tick = 0
        for e in self._events(messages):
            if e.HasField("progress"):
                tick = e.progress.tick
                yield f"{tick}\n"
            else:
                yield ("\n" if tick else "") + e.answer.text

    def _events(self, messages: list[dict]):
        try:
            yield from self.client.run(to_messages(messages))
        except grpc.RpcError as e:
            if e.code() in DOWN:
                raise AgentUnavailable(f"agent: {e.details()}") from e
            raise
