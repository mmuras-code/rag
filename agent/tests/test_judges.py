from unittest.mock import MagicMock

import pytest

from agent.judges import JudgeName, Verdict, make_judge
from agent.judges.aggregate import AggregateJudge
from agent.judges.llm import LlmJudge
from agent.judges.word_limit import MAX_WORDS, WordLimitJudge


def test_judge_names():
    assert [j.value for j in JudgeName] == ["llm", "word_limit", "aggregate"]


def test_make_judge_defaults_to_llm(monkeypatch):
    monkeypatch.delenv("AGENT_JUDGE", raising=False)
    assert isinstance(make_judge(), LlmJudge)


def test_llm_judge_runs_on_sonnet_by_default(monkeypatch):
    monkeypatch.delenv("AGENT_JUDGE", raising=False)
    monkeypatch.delenv("AGENT_JUDGE_MODEL", raising=False)
    assert make_judge().chat.__self__.model == "anthropic/claude-sonnet-5.5"


def test_judge_model_from_env(monkeypatch):
    monkeypatch.delenv("AGENT_JUDGE", raising=False)
    monkeypatch.setenv("AGENT_JUDGE_MODEL", "anthropic/claude-opus-5.5")
    assert make_judge().chat.__self__.model == "anthropic/claude-opus-5.5"


def test_judge_model_rejects_unknown(monkeypatch):
    monkeypatch.setenv("AGENT_JUDGE_MODEL", "nope/nope")
    with pytest.raises(ValueError, match="AGENT_JUDGE_MODEL"):
        make_judge(JudgeName.LLM)


def test_make_judge_from_env(monkeypatch):
    monkeypatch.setenv("AGENT_JUDGE", "word_limit")
    assert isinstance(make_judge(), WordLimitJudge)


def test_make_judge_rejects_unknown(monkeypatch):
    monkeypatch.setenv("AGENT_JUDGE", "nope")
    with pytest.raises(ValueError, match="AGENT_JUDGE"):
        make_judge()


def test_word_limit_passes_at_the_limit():
    v = WordLimitJudge().score("q", " ".join(["w"] * MAX_WORDS))
    assert (v.score, v.feedback) == (100, "")


def test_word_limit_fails_over_the_limit_with_feedback():
    v = WordLimitJudge().score("q", " ".join(["w"] * (MAX_WORDS + 1)))
    assert v.score <= 50
    assert v.feedback == (f"Too long: {MAX_WORDS + 1} words. Answer in at most {MAX_WORDS} words. "
                          "Keep only the most important points.")


def test_word_limit_states_its_requirement():
    assert WordLimitJudge(max_words=10).requirements == ["Answer in at most 10 words."]


def test_word_limit_scores_shorter_failures_higher():
    judge = WordLimitJudge(max_words=10)
    assert judge.score("q", "w " * 12).score > judge.score("q", "w " * 40).score


def fixed(score, feedback=""):
    judge = MagicMock()
    judge.requirements = []
    judge.score.return_value = Verdict(score, feedback)
    return judge


def test_aggregate_takes_lowest_score_and_joins_feedback():
    v = AggregateJudge([fixed(90), fixed(30, "too long : be more crisp"), fixed(60, "cite notes")]).score("q", "a")
    assert v.score == 30
    assert v.feedback == "too long : be more crisp\ncite notes"


def test_aggregate_without_feedback_has_none():
    assert AggregateJudge([fixed(100), fixed(80)]).score("q", "a").feedback == ""


def test_aggregate_calls_every_judge_with_the_answer():
    judges = [fixed(100), fixed(100)]
    AggregateJudge(judges).score("q", "a", "notes")
    for j in judges:
        j.score.assert_called_once_with("q", "a", "notes")


def test_aggregate_skips_a_failing_judge():
    broken = MagicMock()
    broken.score.side_effect = ValueError("no JSON")
    assert AggregateJudge([broken, fixed(70, "x")]).score("q", "a") == Verdict(70, "x")


def test_aggregate_skips_a_judge_that_cannot_reach_openrouter():
    from llm.openrouter import OpenRouterError

    broken = MagicMock()
    broken.score.side_effect = OpenRouterError("503")
    assert AggregateJudge([broken, fixed(70, "x")]).score("q", "a") == Verdict(70, "x")


def test_aggregate_raises_if_every_judge_fails():
    broken = MagicMock()
    broken.score.side_effect = ValueError("no JSON")
    with pytest.raises(ValueError):
        AggregateJudge([broken]).score("q", "a")


def test_make_aggregate_has_word_limit_and_llm(monkeypatch):
    monkeypatch.setenv("AGENT_JUDGE", "aggregate")
    judge = make_judge()
    assert [type(j) for j in judge.judges] == [WordLimitJudge, LlmJudge]


def test_aggregate_collects_requirements_in_order():
    a, b = fixed(100), fixed(100)
    a.requirements, b.requirements = ["one"], ["two"]
    assert AggregateJudge([a, b]).requirements == ["one", "two"]


def test_make_aggregate_tells_the_llm_judge_the_word_limit(monkeypatch):
    monkeypatch.setenv("AGENT_JUDGE", "aggregate")
    judge = make_judge()
    assert judge.requirements == [f"Answer in at most {MAX_WORDS} words."]
    assert f"- Answer in at most {MAX_WORDS} words." in judge.judges[1].prompt
