from orchestrator.clients.stub_client import REPLY, StubClient


def test_always_replies_the_same():
    assert StubClient().chat([{"role": "user", "content": "anything"}]) == REPLY
    assert StubClient().chat([]) == REPLY
