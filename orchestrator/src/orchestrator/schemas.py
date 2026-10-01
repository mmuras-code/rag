"""Request bodies of the OpenAI-compatible API, as far as Open WebUI uses them."""

from pydantic import BaseModel

# The one route: the model id Open WebUI lists in its picker and sends back as `model`.
ROUTE = "personal-rag-v0.1"


class Message(BaseModel):
    role: str
    content: str | list = ""


class ChatRequest(BaseModel):
    model: str
    messages: list[Message]
    stream: bool = False
