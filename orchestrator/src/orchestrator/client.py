"""Client for the orchestrator's OpenAI-compatible API. Callers (integration_tests/, eval/) import
this instead of speaking HTTP themselves. It imports nothing from the server side, only the route id from `schemas`.
"""

import os
from dataclasses import dataclass

import httpx

from orchestrator.schemas import ROUTE

DEFAULT_URL = "http://127.0.0.1:8000"
ID_PREFIX = "chatcmpl-"


@dataclass(frozen=True)
class Reply:
    """An answer and the trace id of the request in Phoenix (project `ml`)."""

    text: str
    trace_id: str


class OrchestratorClient:
    def __init__(self, base_url: str | None = None, api_key: str | None = None, timeout: float = 300,
                 http: httpx.Client | None = None):
        """`base_url` defaults to ORCHESTRATOR_URL, `api_key` to ORCHESTRATOR_API_KEY. `timeout` is
        long because one agent request makes several model calls. `http` is for tests."""
        url = (base_url or os.environ.get("ORCHESTRATOR_URL", DEFAULT_URL)).rstrip("/")
        key = api_key or os.environ.get("ORCHESTRATOR_API_KEY")
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        self.http = http or httpx.Client(base_url=url, headers=headers, timeout=timeout)

    def models(self) -> list[str]:
        """The route ids, as Open WebUI's model picker shows them."""
        r = self.http.get("/v1/models")
        r.raise_for_status()
        return [m["id"] for m in r.json()["data"]]

    def chat(self, messages: list[dict], model: str = ROUTE) -> str:
        """The answer to a conversation of OpenAI-style messages (non-streaming)."""
        return self.reply(messages, model).text

    def reply(self, messages: list[dict], model: str = ROUTE) -> Reply:
        """Like `chat`, plus the request's trace id (the completion id is `chatcmpl-<trace id>`)."""
        r = self.http.post("/v1/chat/completions", json={"model": model, "messages": messages})
        r.raise_for_status()
        body = r.json()
        return Reply(body["choices"][0]["message"]["content"], body["id"].removeprefix(ID_PREFIX))

    def ask(self, question: str, model: str = ROUTE) -> str:
        """The answer to a single user question."""
        return self.chat([{"role": "user", "content": question}], model)
