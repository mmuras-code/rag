from dataclasses import dataclass


@dataclass
class Verdict:
    score: int  # 0-100
    feedback: str  # what to fix, written for the LLM that rewrites the answer; empty if nothing
