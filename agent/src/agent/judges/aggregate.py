"""Aggregate judge: runs every sub-judge on the answer and combines their verdicts.

The score is the lowest sub-judge score, so the answer passes only if every sub-judge passes. The
feedback is the non-empty feedback of the sub-judges, one per line; empty if none had any. A
sub-judge that raises (or cannot reach OpenRouter) is logged and skipped (docs/architecture.md);
if all of them do, this raises. Its requirements are those of every sub-judge, in order.
"""


from common.log import get_logger
from llm.openrouter import OpenRouterError

from agent.judges.verdict import Verdict

log = get_logger("agent.judges.aggregate")


class AggregateJudge:
    def __init__(self, judges: list):
        self.judges = judges
        self.requirements = [r for j in judges for r in j.requirements]

    def score(self, question: str, answer: str, notes: str = "") -> Verdict:
        verdicts = []
        for judge in self.judges:
            try:
                verdicts.append(judge.score(question, answer, notes))
            except (ValueError, KeyError, TypeError, OpenRouterError) as e:
                log.warning("%s failed, skipping it: %s", type(judge).__name__, e)
        if not verdicts:
            raise ValueError("every sub-judge failed")
        feedback = "\n".join(v.feedback for v in verdicts if v.feedback)
        return Verdict(min(v.score for v in verdicts), feedback)
