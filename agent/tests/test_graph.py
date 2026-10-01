import json
from unittest.mock import MagicMock

from common.collection import Collection
from contracts.search.v1.search_pb2 import Result

from agent.graph import DECIDE_PROMPT, GRADE_PROMPT, MAX_GENERATIONS, build_graph, run
from agent.judges import Verdict

QUESTION = [{"role": "user", "content": "what is rrf"}]


def fakes(decide_reply, judge_scores, results=(), grade_reply=None, decide_replies=None):
    """chat answers by prompt: decide (`decide_replies` in order, then `decide_reply`), grade
    (`grade_reply`, default: every note relevant) and generate ("answer 1", "answer 2", ...). `calls`
    holds the generate calls only; `all_calls` every call. The judge returns the scores in order."""
    answers = iter(["answer 1", "answer 2", "answer 3", "answer 4"])
    decides = iter(decide_replies or [])
    calls, all_calls = [], []

    def chat(messages):
        all_calls.append(messages)
        system = messages[0]["content"]
        if system.startswith(DECIDE_PROMPT):
            return next(decides, decide_reply)
        if system == GRADE_PROMPT:
            return grade_reply if grade_reply is not None else json.dumps({"relevant": [r.path for r in results]})
        calls.append(messages)
        return next(answers)

    judge = MagicMock()
    judge.requirements = []
    judge.score.side_effect = [Verdict(s, f"fix {s}") for s in judge_scores]
    search = MagicMock()
    search.query.return_value = list(results)
    chat.all_calls = all_calls
    return chat, calls, judge, search


def test_no_notes_needed_skips_search_and_passes_first_try():
    chat, calls, judge, search = fakes('{"route": "none", "query": ""}', [80])
    assert run(QUESTION, build_graph(chat, search, judge)) == "answer 1"
    search.query.assert_not_called()
    assert len(chat.all_calls) == 2  # decide + one generate


def test_relevant_notes_go_into_context_and_to_the_judge():
    results = [Result(path="rag/rrf.md", score=0.03, content="rrf body", similarity=0.8),
               Result(path="x/other.md", score=0.02, content="other", similarity=0.1)]
    chat, calls, judge, search = fakes('{"route": "ml", "query": "reciprocal rank fusion"}', [80], results)
    run(QUESTION, build_graph(chat, search, judge))
    search.query.assert_called_once_with("reciprocal rank fusion", k=5, collection="ml")
    system = calls[0][0]["content"]
    assert '<note path="rag/rrf.md">' in system and "x/other.md" not in system
    assert "rag/rrf.md" in judge.score.call_args.args[2]


def test_low_score_retries_with_feedback_until_pass():
    chat, calls, judge, search = fakes('{"route": "none"}', [30, 70])
    assert run(QUESTION, build_graph(chat, search, judge)) == "answer 2"
    assert calls[1][-2]["role"] == "assistant" and calls[1][-2]["content"] == "answer 1"
    assert calls[1][-1]["role"] == "user" and "fix 30" in calls[1][-1]["content"]


def test_score_of_exactly_50_does_not_pass():
    chat, _calls, judge, search = fakes('{"route": "none"}', [50, 51])
    assert run(QUESTION, build_graph(chat, search, judge)) == "answer 2"


def test_stops_at_max_generations_and_returns_best_answer():
    chat, _calls, judge, search = fakes('{"route": "none"}', [20, 45, 10])
    assert run(QUESTION, build_graph(chat, search, judge)) == "answer 2"
    assert judge.score.call_count == MAX_GENERATIONS


def test_unparseable_decide_searches_anyway():
    chat, _calls, judge, search = fakes("sure, notes would help", [80])
    run(QUESTION, build_graph(chat, search, judge))
    search.query.assert_called_once_with("what is rrf", k=5, collection="")


def test_unparseable_judge_accepts_answer():
    chat, _calls, judge, search = fakes('{"route": "none"}', [])
    judge.score.side_effect = ValueError("no JSON")
    assert run(QUESTION, build_graph(chat, search, judge)) == "answer 1"


def test_judge_requirements_go_into_the_generate_prompt():
    chat, calls, judge, search = fakes('{"route": "none"}', [80])
    judge.requirements = ["Answer in at most 100 words."]
    run(QUESTION, build_graph(chat, search, judge))
    assert "- Answer in at most 100 words." in calls[0][0]["content"]


def test_no_requirements_leaves_the_generate_prompt_alone():
    chat, calls, judge, search = fakes('{"route": "none"}', [80])
    run(QUESTION, build_graph(chat, search, judge))
    assert "Requirements" not in calls[0][0]["content"]


def test_run_traces_agent_span_with_telemetry_attributes(spans):
    chat, _calls, judge, search = fakes('{"route": "none"}', [30, 70])
    run(QUESTION, build_graph(chat, search, judge))
    agent = next(s for s in spans.get_finished_spans() if s.name == "agent")
    assert agent.attributes["agent.termination_reason"] == "passed"
    assert agent.attributes["agent.retrieval_skipped"] is True
    assert agent.attributes["agent.iterations"] == 2
    assert agent.attributes["output.value"] == "answer 2"


def test_run_traces_iteration_limit(spans):
    chat, _calls, judge, search = fakes('{"route": "none"}', [20, 45, 10])
    run(QUESTION, build_graph(chat, search, judge))
    agent = next(s for s in spans.get_finished_spans() if s.name == "agent")
    assert agent.attributes["agent.termination_reason"] == "iteration_limit"


def test_unreachable_judge_accepts_answer_as_judge_unavailable(spans):
    from llm.openrouter import OpenRouterError

    chat, _calls, judge, search = fakes('{"route": "none"}', [])
    judge.score.side_effect = OpenRouterError("503")
    assert run(QUESTION, build_graph(chat, search, judge)) == "answer 1"
    agent = next(s for s in spans.get_finished_spans() if s.name == "agent")
    assert agent.attributes["agent.termination_reason"] == "judge_unavailable"


def test_unreachable_search_is_a_service_fault():
    import grpc
    import pytest
    from observability import ServiceFault

    from agent.graph import SearchUnavailable

    chat, _calls, judge, search = fakes('{"route": "ml", "query": "rrf"}', [80])
    class Down(grpc.RpcError):
        def code(self):
            return grpc.StatusCode.UNAVAILABLE

        def details(self):
            return "connection refused"

    search.query.side_effect = Down()
    with pytest.raises(SearchUnavailable, match="UNAVAILABLE: connection refused") as e:
        run(QUESTION, build_graph(chat, search, judge))
    assert isinstance(e.value, ServiceFault)


RRF = Result(path="rag/rrf.md", score=0.03, content="rrf body", similarity=0.6)
NEAR = Result(path="rag/near.md", score=0.02, content="near body", similarity=0.4)
JUNK = Result(path="x/junk.md", score=0.01, content="junk", similarity=0.05)


def test_floor_drops_junk_before_grading():
    chat, _calls, judge, search = fakes('{"route": "ml", "query": "rrf"}', [80], [RRF, JUNK])
    run(QUESTION, build_graph(chat, search, judge))
    grade_call = next(c for c in chat.all_calls if c[0]["content"] == GRADE_PROMPT)
    assert "rag/rrf.md" in grade_call[1]["content"] and "x/junk.md" not in grade_call[1]["content"]


def test_grade_keeps_only_relevant_notes():
    chat, calls, judge, search = fakes('{"route": "ml", "query": "rrf"}', [80], [RRF, NEAR],
                                       grade_reply='{"relevant": ["rag/rrf.md"]}')
    run(QUESTION, build_graph(chat, search, judge))
    system = calls[0][0]["content"]
    assert "rag/rrf.md" in system and "rag/near.md" not in system


def test_unparseable_grade_keeps_every_candidate():
    chat, calls, judge, search = fakes('{"route": "ml", "query": "rrf"}', [80], [RRF, NEAR],
                                       grade_reply="both look fine")
    run(QUESTION, build_graph(chat, search, judge))
    assert "rag/rrf.md" in calls[0][0]["content"] and "rag/near.md" in calls[0][0]["content"]


def test_nothing_relevant_tells_the_model_and_is_traced(spans):
    chat, calls, judge, search = fakes('{"route": "ml", "query": "lora"}', [80], [NEAR],
                                       grade_reply='{"relevant": []}')
    run(QUESTION, build_graph(chat, search, judge))
    assert "none is relevant" in calls[0][0]["content"] and "<note" not in calls[0][0]["content"]
    assert "none was relevant" in judge.score.call_args.args[2]
    agent = next(s for s in spans.get_finished_spans() if s.name == "agent")
    assert agent.attributes["agent.retrieval_empty"] is True
    assert agent.attributes["agent.retrieval_skipped"] is False


def test_no_search_is_not_retrieval_empty(spans):
    chat, _calls, judge, search = fakes('{"route": "none"}', [80])
    run(QUESTION, build_graph(chat, search, judge))
    agent = next(s for s in spans.get_finished_spans() if s.name == "agent")
    assert agent.attributes["agent.retrieval_empty"] is False


def test_retry_searches_again_with_a_new_query_and_keeps_earlier_notes(spans):
    chat, calls, judge, search = fakes(
        "", [30, 80], grade_reply='{"relevant": ["rag/rrf.md", "rag/near.md"]}',
        decide_replies=['{"route": "ml", "query": "rrf"}', '{"route": "ml", "query": "rrf constant k"}'])
    search.query.side_effect = [[RRF], [NEAR]]
    assert run(QUESTION, build_graph(chat, search, judge)) == "answer 2"
    assert [c.args[0] for c in search.query.call_args_list] == ["rrf", "rrf constant k"]
    retry_decide = [c for c in chat.all_calls if c[0]["content"].startswith(DECIDE_PROMPT)][1]
    assert "fix 30" in retry_decide[0]["content"] and '"rrf"' in retry_decide[0]["content"]
    assert "rag/rrf.md" in calls[1][0]["content"] and "rag/near.md" in calls[1][0]["content"]
    agent = next(s for s in spans.get_finished_spans() if s.name == "agent")
    assert agent.attributes["agent.searches"] == 2


def test_retry_does_not_repeat_a_query():
    chat, _calls, judge, search = fakes('{"route": "ml", "query": "rrf"}', [30, 80], [RRF])
    run(QUESTION, build_graph(chat, search, judge))
    search.query.assert_called_once()


def test_retry_without_search_rewrites_with_the_same_notes():
    chat, calls, judge, search = fakes(
        "", [30, 80], [RRF], decide_replies=['{"route": "ml", "query": "rrf"}', '{"route": "none"}'])
    run(QUESTION, build_graph(chat, search, judge))
    search.query.assert_called_once()
    assert "rag/rrf.md" in calls[1][0]["content"]



def test_test_route_searches_only_the_test_collection():
    chat, _calls, judge, search = fakes('{"route": "test", "query": "favorite number"}', [80])
    run([{"role": "user", "content": "Test question: what is my favorite number?"}], build_graph(chat, search, judge))
    search.query.assert_called_once_with("favorite number", k=5, collection="test")


def test_unknown_route_searches_every_collection():
    chat, _calls, judge, search = fakes('{"route": "finance", "query": "budget"}', [80])
    run(QUESTION, build_graph(chat, search, judge))
    search.query.assert_called_once_with("what is rrf", k=5, collection="")


def test_routing_prompt_describes_every_collection():
    for collection in Collection:
        assert f'"{collection}"' in DECIDE_PROMPT
