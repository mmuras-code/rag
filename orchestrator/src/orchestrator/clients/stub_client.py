"""Stub LLM client: calls nothing and returns a fixed reply. For wiring tests without a model."""

REPLY = "This is the stub backend."


class StubClient:
    def chat(self, messages: list[dict]) -> str:
        return REPLY
