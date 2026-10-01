"""Word-limit judge: the answer must be at most MAX_WORDS words. Plain code, no LLM."""

from agent.judges.verdict import Verdict

MAX_WORDS = 100


class WordLimitJudge:
    def __init__(self, max_words: int = MAX_WORDS):
        self.max_words = max_words
        self.requirements = [f"Answer in at most {max_words} words."]

    def score(self, question: str, answer: str, notes: str = "") -> Verdict:
        words = len(answer.split())
        if words <= self.max_words:
            return Verdict(100, "")
        # Failing scores stay at or below 50 (the graph's pass mark) and are higher the closer the
        # answer is to the limit, so the best-scored answer is the shortest one.
        feedback = f"Too long: {words} words. {self.requirements[0]} Keep only the most important points."
        return Verdict(min(50, 50 * self.max_words // words), feedback)
