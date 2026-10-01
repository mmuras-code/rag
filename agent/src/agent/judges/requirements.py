"""Requirements: the rules a judge enforces, as text for a prompt.

A judge lists them in its `requirements` attribute, so the same words reach the model that writes
the answer (the generate prompt) and the model that judges it (the LLM judge). Without them the
writer only learns a rule after breaking it, and the LLM judge asks for things that break it.
"""


def requirements_prompt(requirements: list[str]) -> str:
    """A prompt section listing the requirements; empty if there are none."""
    if not requirements:
        return ""
    lines = "\n".join(f"- {r}" for r in requirements)
    return f"## Requirements\n\nThe answer must meet every one of these:\n\n{lines}"
