import json

from evals import dataset
from evals.evaluators import (
    TraceUsage,
    expected_words,
    failed_checks,
    note_cited,
    summarize,
    trace_evaluators,
    usage_evaluators,
)

NOTE = "theoretical/rag/query_processing_notes.md"


def test_expected_words_is_the_share_found():
    assert expected_words({"answer": "Usually K=60 in RRF"}, {"expect": ["60", "rank"]}) == 0.5
    assert expected_words({"answer": "anything"}, {"expect": []}) == 1.0


def test_note_questions_must_cite_an_expected_note():
    assert note_cited({"answer": f"k is 60 [{NOTE}]"}, {"notes": [NOTE]})
    assert not note_cited({"answer": "k is 60 [other/note.md]"}, {"notes": [NOTE]})
    assert not note_cited({"answer": "k is 60"}, {"notes": [NOTE]})


def test_a_citation_by_file_name_counts():
    assert note_cited({"answer": "k is 60 [query_processing_notes.md]"}, {"notes": [NOTE]})
    assert not note_cited({"answer": "k is 60 [other_notes.md]"}, {"notes": [NOTE]})


def test_other_questions_must_cite_nothing():
    assert note_cited({"answer": "Warsaw."}, {"notes": []})
    assert not note_cited({"answer": f"Warsaw [{NOTE}]"}, {"notes": []})


def span(kind, **attributes):
    return {"name": "x", "span_kind": kind, "attributes": attributes}


def test_summarize_adds_up_llm_spans():
    spans = [span("LLM", **{"llm.cost.total": 0.001, "llm.token_count.total": 100, "llm.model_name": "m"}),
             span("LLM", **{"llm.cost.total": 0.002, "llm.token_count.total": 50, "llm.model_name": "m"}),
             span("CHAIN")]
    assert summarize(spans) == {"cost_usd": 0.003, "tokens": 150, "llm_calls": 2, "models": ["m"],
                                "termination_reason": "unknown", "retrieved": [], "in_context": []}


class FakeSpans:
    def __init__(self, batches):
        self.batches, self.calls = batches, 0

    def get_spans(self, **kwargs):
        self.calls += 1
        return self.batches[min(self.calls, len(self.batches)) - 1]


def test_usage_waits_for_the_agent_span_and_caches():
    agent = {"name": "agent", "span_kind": "AGENT", "attributes": {}}
    llm = span("LLM", **{"llm.cost.total": 0.01, "llm.token_count.total": 10})
    client = type("C", (), {})()
    client.spans = FakeSpans([[llm], [llm, agent]])
    evaluators = usage_evaluators(TraceUsage(client, poll_seconds=0))
    assert evaluators["cost_usd"]({"trace_id": "t"}) == 0.01
    assert evaluators["llm_calls"]({"trace_id": "t"}) == 1
    assert client.spans.calls == 2  # one wait, then cached


def test_golden_cases_are_well_formed():
    for case in dataset.load(dataset.DATASETS / "golden.jsonl"):
        assert set(case) == {"question", "expect", "notes"}, case
        assert all(n.endswith(".md") for n in case["notes"])


def test_phoenix_name_changes_with_content(tmp_path):
    f = tmp_path / "golden.jsonl"
    f.write_text(json.dumps({"question": "a", "expect": [], "notes": []}))
    first = dataset.phoenix_name(f)
    f.write_text(json.dumps({"question": "b", "expect": [], "notes": []}))
    assert first.startswith("golden-") and dataset.phoenix_name(f) != first


class FixedUsage:
    def __init__(self, **facts):
        self.facts = {"termination_reason": "passed", "retrieved": [], "in_context": [], **facts}

    def __call__(self, trace_id):
        return self.facts


def test_note_followed_through_retrieval_and_context():
    out, exp = {"trace_id": "t"}, {"notes": [NOTE]}
    lost_in_grading = trace_evaluators(FixedUsage(retrieved=[NOTE, "x.md"], in_context=["x.md"]))
    assert lost_in_grading["note_retrieved"](out, exp) is True
    assert lost_in_grading["note_in_context"](out, exp) is False
    never_found = trace_evaluators(FixedUsage(retrieved=["x.md"]))
    assert never_found["note_retrieved"](out, exp) is False


def test_off_topic_question_must_end_with_no_notes_in_context():
    out, exp = {"trace_id": "t"}, {"notes": []}
    searched_and_graded_out = trace_evaluators(FixedUsage(retrieved=["x.md"]))
    assert searched_and_graded_out["note_retrieved"](out, exp) is True
    assert searched_and_graded_out["note_in_context"](out, exp) is True
    assert trace_evaluators(FixedUsage(in_context=["x.md"]))["note_in_context"](out, exp) is False


def test_judge_unavailable_is_not_judged():
    assert trace_evaluators(FixedUsage())["judged"]({"trace_id": "t"}) is True
    assert trace_evaluators(FixedUsage(termination_reason="judge_unavailable"))["judged"]({"trace_id": "t"}) is False


def test_summarize_reads_the_agent_and_retrieve_spans():
    spans = [{"name": "agent", "span_kind": "AGENT",
              "attributes": {"agent.termination_reason": "passed", "agent.note_paths": [NOTE]}},
             {"name": "retrieve", "span_kind": "CHAIN", "attributes": {"search.note_paths": [NOTE, "x.md"]}},
             {"name": "retrieve", "span_kind": "CHAIN", "attributes": {"search.note_paths": ["y.md"]}}]
    facts = summarize(spans)
    assert facts["termination_reason"] == "passed"
    assert facts["retrieved"] == sorted([NOTE, "x.md", "y.md"]) and facts["in_context"] == [NOTE]


def trace(retrieved=(), in_context=(), ending="passed"):
    return {"retrieved": list(retrieved), "in_context": list(in_context), "termination_reason": ending}


def test_failed_checks_is_empty_when_the_note_reaches_the_answer():
    expected = {"expect": ["60"], "notes": [NOTE]}
    output = {"answer": f"k is 60 [{NOTE}]"}
    assert failed_checks(output, expected, trace([NOTE], [NOTE])) == []


def test_failed_checks_names_every_stage_that_lost_the_note():
    expected = {"expect": ["60"], "notes": [NOTE]}
    output = {"answer": "k is usually 60"}  # right from general knowledge, no notes
    assert failed_checks(output, expected, trace()) == ["note_retrieved", "note_in_context", "note_cited"]
    assert failed_checks(output, expected, trace([NOTE], [NOTE], "judge_unavailable")) == ["note_cited", "judged"]
