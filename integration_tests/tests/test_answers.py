"""Smoke test of the whole system: ask the orchestrator each question in ../questions.json and
check that a sensible answer comes back.

The questions have short, unambiguous answers, so a working system always contains the expected
words (case-insensitive, whole words). A failure means something is broken, not that an answer
is mediocre: answer quality is scored in eval/. Each question runs the whole agent, so a few
OpenRouter model calls are made per question.
"""

import json
import re
from pathlib import Path

import pytest

QUESTIONS = json.loads((Path(__file__).resolve().parents[1] / "questions.json").read_text())


@pytest.mark.parametrize("case", QUESTIONS, ids=[q["question"] for q in QUESTIONS])
def test_answer_is_correct(orchestrator, case):
    answer = orchestrator.ask(case["question"])
    missing = [w for w in case["expect"] if not re.search(rf"\b{re.escape(w)}\b", answer, re.IGNORECASE)]
    assert not missing, f"missing {missing} in answer: {answer!r}"
