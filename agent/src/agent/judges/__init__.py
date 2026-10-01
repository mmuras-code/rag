"""Pluggable judges for the graph's judge step.

A judge scores an answer 0-100 and says what to fix. The graph ends when the score is above
PASS_SCORE (agent/graph.py), so a failing judge returns 50 or less. `JudgeName` lists the judges;
AGENT_JUDGE picks one (`llm` by default). The LLM judge runs on AGENT_JUDGE_MODEL (Sonnet by
default), a stronger model than the one writing the answer, so it is not grading its own work. A judge's `requirements` are the rules it enforces, as text
(judges/requirements.py); the graph puts them into the generate prompt.
"""

import os
from enum import Enum
from typing import Protocol

from llm import OpenRouterClient
from llm.openrouter import OpenRouterModel

from agent.judges.verdict import Verdict

DEFAULT_JUDGE_MODEL = OpenRouterModel.SONNET


class Judge(Protocol):
    requirements: list[str]  # rules this judge enforces, told to the writer up front; may be empty

    def score(self, question: str, answer: str, notes: str = "") -> Verdict:
        """Raises ValueError if it cannot judge; the graph then accepts the answer."""
        ...


class JudgeName(str, Enum):
    LLM = "llm"  # judges/llm.py: a model scores the answer with a fixed rubric
    WORD_LIMIT = "word_limit"  # judges/word_limit.py: the answer is at most 100 words
    AGGREGATE = "aggregate"  # judges/aggregate.py: all of the above, lowest score, feedback joined


def judge_model() -> OpenRouterModel:
    """AGENT_JUDGE_MODEL as a model ID, or Sonnet. Unknown IDs fail."""
    value = os.environ.get("AGENT_JUDGE_MODEL", DEFAULT_JUDGE_MODEL)
    try:
        return OpenRouterModel(value)
    except ValueError:
        raise ValueError(f"AGENT_JUDGE_MODEL={value!r}; expected one of {[m.value for m in OpenRouterModel]}") from None


def make_judge(name: JudgeName | str | None = None) -> Judge:
    """The named judge, or the one AGENT_JUDGE names. Raises ValueError for an unknown name."""
    value = name or os.environ.get("AGENT_JUDGE", JudgeName.LLM.value)
    try:
        name = JudgeName(value)
    except ValueError:
        raise ValueError(f"AGENT_JUDGE={value!r}; expected one of {[j.value for j in JudgeName]}") from None
    from agent.judges.aggregate import AggregateJudge
    from agent.judges.llm import LlmJudge
    from agent.judges.word_limit import WordLimitJudge

    def llm_judge(**kwargs):
        return LlmJudge(chat=OpenRouterClient(judge_model()).chat, **kwargs)

    if name is JudgeName.LLM:
        return llm_judge()
    if name is JudgeName.WORD_LIMIT:
        return WordLimitJudge()
    # Cheap programmatic judge first, then the LLM, which is told the limit so it does not ask for more.
    word_limit = WordLimitJudge()
    return AggregateJudge([word_limit, llm_judge(requirements=word_limit.requirements)])


__all__ = ["Judge", "JudgeName", "Verdict", "judge_model", "make_judge"]
