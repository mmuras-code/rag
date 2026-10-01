"""The agent.v1.Agent service over real gRPC, called through the generated client."""

import time
from concurrent import futures

import grpc
import pytest
from contracts.agent import AgentClient
from contracts.agent.v1 import agent_pb2, agent_pb2_grpc
from observability import ServiceFault

from agent.server import AgentService

QUESTION = [agent_pb2.Message(role=agent_pb2.ROLE_USER, content="what is rrf")]


class FakeGraph:
    def __init__(self, answer="the answer", delay=0.0, error=None):
        self.answer, self.delay, self.error, self.seen = answer, delay, error, None

    def invoke(self, state):
        self.seen = state["messages"]
        time.sleep(self.delay)
        if self.error:
            raise self.error
        return {"best_answer": self.answer}


@pytest.fixture
def serve():
    servers = []

    def start(graph, tick_seconds=5) -> AgentClient:
        server = grpc.server(futures.ThreadPoolExecutor(max_workers=2))
        agent_pb2_grpc.add_AgentServicer_to_server(AgentService(graph, tick_seconds), server)
        port = server.add_insecure_port("127.0.0.1:0")
        server.start()
        servers.append(server)
        return AgentClient(f"127.0.0.1:{port}")

    yield start
    for s in servers:
        s.stop(None)


def test_ticks_while_graph_runs_then_sends_answer(serve):
    events = list(serve(FakeGraph(delay=0.35), tick_seconds=0.1).run(QUESTION))
    assert [e.progress.tick for e in events[:3]] == [1, 2, 3]
    assert all(e.WhichOneof("event") == "progress" for e in events[:-1])
    assert events[-1].answer.text == "the answer"


def test_fast_graph_sends_only_the_answer(serve):
    events = list(serve(FakeGraph("quick")).run(QUESTION))
    assert [e.WhichOneof("event") for e in events] == ["answer"]
    assert events[0].answer.text == "quick"


def test_messages_reach_the_graph_as_role_and_text(serve):
    graph = FakeGraph()
    messages = [agent_pb2.Message(role=agent_pb2.ROLE_SYSTEM, content="be brief"), *QUESTION]
    list(serve(graph).run(messages))
    assert graph.seen == [{"role": "system", "content": "be brief"}, {"role": "user", "content": "what is rrf"}]


@pytest.mark.parametrize("error, code", [
    (ServiceFault("search failed"), grpc.StatusCode.UNAVAILABLE),
    (RuntimeError("bug"), grpc.StatusCode.INTERNAL),
])
def test_errors_become_status_codes(serve, error, code):
    with pytest.raises(grpc.RpcError) as e:
        list(serve(FakeGraph(error=error)).run(QUESTION))
    assert e.value.code() == code
    assert str(error) in e.value.details()


@pytest.mark.parametrize("messages", [[], [agent_pb2.Message(content="no role")]])
def test_malformed_request_is_invalid_argument(serve, messages):
    with pytest.raises(grpc.RpcError) as e:
        list(serve(FakeGraph()).run(messages))
    assert e.value.code() == grpc.StatusCode.INVALID_ARGUMENT
