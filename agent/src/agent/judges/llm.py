"""LLM judge: a model scores the answer 0-100 with a fixed rubric. Uses `llm.OpenRouterClient` by default."""

import json
import re

from common.log import get_logger
from llm import OpenRouterClient

from agent.judges.requirements import requirements_prompt
from agent.judges.verdict import Verdict

log = get_logger("agent.judges.llm")

JUDGE_PROMPT = """You are a strict, impartial judge of answers written by an AI assistant. You do \
not answer the question yourself. You score the answer and explain what would improve it.

## Inputs

You receive the user's QUESTION, the NOTES the assistant was given (or "(no notes used)"), and \
the ANSWER to judge. A Requirements section at the end, if present, lists rules the assistant was \
told to follow. Other judges check those rules; judge detail and completeness within them, and \
never ask for a fix that would break one.

## Rubric (100 points)

1. Correctness (40): the claims are true. Check them against the notes when notes are given, \
otherwise against well-established knowledge.
2. Addresses the question (25): answers what was actually asked, all parts of it, at the level \
of detail the question calls for.
3. Grounding (20): when notes are given, the answer uses them where relevant, does not \
contradict them, and cites the notes it used as [path]. When no notes are given, award these \
points under Correctness instead.
4. Clarity (15): well organised, direct and no longer than needed. Length is not a merit.

## Hard caps (apply after summing)

- A factual error in the core of the answer: at most 40.
- Ignores or misreads the question: at most 20.
- Attributes to the notes something the notes do not say, or cites a path not in the notes: \
at most 40.
- Refuses or deflects a reasonable question: at most 20.

## Score bands

- 90-100: correct, complete, well grounded; nothing meaningful to fix.
- 70-89: correct and useful, with minor gaps or rough edges.
- 51-69: acceptable but with clear gaps or weak grounding.
- 30-50: significant problems; must be rewritten.
- 0-29: wrong, off-topic or unhelpful.

## Feedback

Write the feedback for the assistant that will rewrite the answer: up to 5 concrete, actionable \
fixes, most important first, each naming what is wrong and what to do instead. Do not praise. \
Use an empty string when the score is 90 or above.

## Output

Reply with exactly one JSON object and nothing else: no prose, no code fence.
{"score": <integer 0-100>, "feedback": "<fixes, or empty string>"}"""


def parse_verdict(reply: str) -> Verdict:
    """The first JSON object in the reply, as a Verdict. Raises ValueError if there is none."""
    match = re.search(r"\{.*\}", reply, re.DOTALL)
    if not match:
        raise ValueError(f"no JSON object in judge reply: {reply[:200]!r}")
    data = json.loads(match.group(0))
    score = int(data["score"])
    if not 0 <= score <= 100:
        raise ValueError(f"score out of range: {score}")
    return Verdict(score, str(data.get("feedback") or ""))


class LlmJudge:
    """`requirements` are rules other judges enforce; they go into the rubric prompt so this judge
    does not ask for fixes that break them. It enforces none itself."""

    def __init__(self, chat=None, requirements: list[str] | None = None):
        self.chat = chat or OpenRouterClient().chat
        self.prompt = "\n\n".join(filter(None, [JUDGE_PROMPT, requirements_prompt(requirements or [])]))
        self.requirements: list[str] = []

    def score(self, question: str, answer: str, notes: str = "") -> Verdict:
        """Raises ValueError if the reply cannot be parsed; the caller decides what to do then."""
        reply = self.chat([
            {"role": "system", "content": self.prompt},
            {"role": "user", "content": f"QUESTION:\n{question}\n\nNOTES:\n{notes or '(no notes used)'}"
                                        f"\n\nANSWER:\n{answer}"},
        ])
        return parse_verdict(reply)
