import grpc
import pytest
from contracts.agent.v1.agent_pb2 import ROLE_SYSTEM, ROLE_USER, Answer, Message, Progress, RunEvent
from observability import ServiceFault

from orchestrator.clients.agent_client import AgentBackend, AgentUnavailable, to_messages

QUESTION = [{"role": "user", "content": "hi"}]


class FakeClient:
    def __init__(self, events=(), error=None):
        self.events, self.error, self.seen = events, error, None

    def run(self, messages):
        self.seen = list(messages)
        yield from self.events
        if self.error:
            raise self.error


class RpcError(grpc.RpcError):
    def __init__(self, code, details="down"):
        self._code, self._details = code, details

    def code(self):
        return self._code

    def details(self):
        return self._details


def progress(tick):
    return RunEvent(progress=Progress(tick=tick))


def answer(text):
    return RunEvent(answer=Answer(text=text))


def test_messages_become_the_contracts_messages():
    messages = [{"role": "system", "content": "be brief"}, {"role": "tool", "content": "x"},
                {"role": "user", "content": [{"type": "text", "text": "a"}, {"type": "image_url"},
                                             {"type": "text", "text": "b"}]}]
    assert to_messages(messages) == [Message(role=ROLE_SYSTEM, content="be brief"),
                                     Message(role=ROLE_USER, content="a\nb")]


def test_stream_sends_a_counter_line_per_progress_event_then_the_answer():
    client = FakeClient([progress(1), progress(2), answer("the answer")])
    assert list(AgentBackend(client).stream(QUESTION)) == ["1\n", "2\n", "\nthe answer"]
    assert client.seen == [Message(role=ROLE_USER, content="hi")]


def test_fast_answer_is_one_piece():
    assert list(AgentBackend(FakeClient([answer("quick")])).stream(QUESTION)) == ["quick"]


def test_chat_returns_only_the_answer():
    assert AgentBackend(FakeClient([progress(1), answer("the answer")])).chat(QUESTION) == "the answer"


@pytest.mark.parametrize("code", [grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED])
def test_agent_down_is_a_service_fault(code):
    backend = AgentBackend(FakeClient(error=RpcError(code, "search failed: connection refused")))
    with pytest.raises(AgentUnavailable, match="search failed: connection refused") as e:
        backend.chat(QUESTION)
    assert isinstance(e.value, ServiceFault)


def test_other_rpc_errors_are_raised_as_is():
    with pytest.raises(grpc.RpcError):
        list(AgentBackend(FakeClient(error=RpcError(grpc.StatusCode.INTERNAL))).stream(QUESTION))
