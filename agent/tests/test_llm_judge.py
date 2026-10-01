from unittest.mock import MagicMock

import pytest

from agent.judges.llm import JUDGE_PROMPT, LlmJudge, parse_verdict


def test_score_sends_rubric_and_inputs():
    chat = MagicMock(return_value='{"score": 72, "feedback": "cite the note"}')
    v = LlmJudge(chat).score("what is rrf", "an answer", '<note path="a.md">x</note>')
    assert (v.score, v.feedback) == (72, "cite the note")
    system, user = chat.call_args.args[0]
    assert system == {"role": "system", "content": JUDGE_PROMPT}
    assert "QUESTION:\nwhat is rrf" in user["content"] and "ANSWER:\nan answer" in user["content"]
    assert 'path="a.md"' in user["content"]


def test_requirements_go_into_the_rubric_but_are_not_its_own():
    chat = MagicMock(return_value='{"score": 90, "feedback": ""}')
    judge = LlmJudge(chat, requirements=["Answer in at most 100 words."])
    judge.score("q", "a")
    system = chat.call_args.args[0][0]["content"]
    assert system.startswith(JUDGE_PROMPT) and system.endswith("- Answer in at most 100 words.")
    assert judge.requirements == []


def test_no_notes_is_stated():
    chat = MagicMock(return_value='{"score": 90, "feedback": ""}')
    LlmJudge(chat).score("q", "a")
    assert "(no notes used)" in chat.call_args.args[0][1]["content"]


def test_parse_tolerates_code_fence():
    assert parse_verdict('```json\n{"score": 55, "feedback": "x"}\n```').score == 55


@pytest.mark.parametrize("reply", ["no json here", '{"score": 150}', '{"feedback": "x"}'])
def test_parse_rejects_bad_replies(reply):
    with pytest.raises((ValueError, KeyError)):
        parse_verdict(reply)
