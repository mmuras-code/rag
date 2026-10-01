"""Response bodies of the OpenAI-compatible API: a whole completion, SSE chunks, and errors."""

import json
import time
from collections.abc import Iterable, Iterator

from fastapi.responses import StreamingResponse
from observability import ServiceFault


def completion(request_id: str, model: str, text: str) -> dict:
    return {
        "id": request_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
    }


def chunk(request_id: str, model: str, delta: dict, finish: str | None = None) -> str:
    body = {
        "id": request_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }
    return f"data: {json.dumps(body)}\n\n"


DONE = "data: [DONE]\n\n"


def error(exc: Exception) -> dict:
    """OpenAI's error body. A `ServiceFault` names itself (Open WebUI shows the message); anything
    else is reported without its details."""
    if isinstance(exc, ServiceFault):
        return {"error": {"message": str(exc), "type": "service_unavailable", "code": type(exc).__name__}}
    return {"error": {"message": "internal server error", "type": "server_error", "code": type(exc).__name__}}


class EventStream(StreamingResponse):
    """The SSE answer: a role chunk, one chunk per piece, a stop chunk, then [DONE].

    If the pieces fail after the stream started, the client gets an error event and [DONE] instead
    of a cut connection, and the exception is raised once the response is complete. Raising it
    inside the generator would cut the body (no end of the chunked encoding); swallowing it would
    count the request as a success, since telemetry classifies by the exception (see
    ../../docs/telemetry.md).
    """

    def __init__(self, request_id: str, model: str, pieces: Iterable[str]):
        self.failure: Exception | None = None
        super().__init__(self._events(request_id, model, pieces), media_type="text/event-stream")

    def _events(self, request_id: str, model: str, pieces: Iterable[str]) -> Iterator[str]:
        try:
            yield chunk(request_id, model, {"role": "assistant"})
            for piece in pieces:
                yield chunk(request_id, model, {"content": piece})
            yield chunk(request_id, model, {}, finish="stop")
        except Exception as exc:
            self.failure = exc
            yield f"data: {json.dumps(error(exc))}\n\n"
        yield DONE

    async def __call__(self, scope, receive, send) -> None:
        await super().__call__(scope, receive, send)
        if self.failure is not None:
            raise self.failure
