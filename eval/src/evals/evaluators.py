"""Evaluators: each scores one task output. Phoenix shows the mean of each per experiment.

Quality comes from the answer; process (cost, tokens, model calls) and the retrieval path are read
back from the request's trace in Phoenix (project `ml`), where `llm/` records each model call's
billed cost (`llm.cost.total`) and the agent the notes it searched, kept and how it ended (see
../../../docs/telemetry.md).

For a question about the notes, three evaluators follow an expected note down the pipeline, so a
bad answer can be pinned on the stage that lost it: `note_retrieved` (search returned it),
`note_in_context` (grading kept it, so the writer saw it) and `note_cited` (the answer cites it).
"""

import re
import time

CITATION = re.compile(r"\[([^\[\]]+?\.md)\]")
TRACE_PROJECT = "ml"


def expected_words(output: dict, expected: dict) -> float:
    """Share of the expected words or phrases that appear in the answer (1.0 when none are set)."""
    words = expected["expect"]
    if not words:
        return 1.0
    answer = output["answer"].lower()
    return sum(w.lower() in answer for w in words) / len(words)


def cited_notes(answer: str) -> set[str]:
    """Note paths the answer cites as [path.md]."""
    return set(CITATION.findall(answer))


def note_cited(output: dict, expected: dict) -> bool:
    """Questions about the notes cite at least one expected note; others cite none.

    The writer cites either the vault path or only the file name, so both count."""
    cited = cited_notes(output["answer"])
    if not expected["notes"]:
        return not cited
    return any(c == note or c == note.rsplit("/", 1)[-1] for c in cited for note in expected["notes"])


class TraceUsage:
    """Cost, tokens and model calls of one request, summed over its LLM spans in Phoenix.

    Spans arrive in batches a few seconds after the request, so a lookup waits until the trace's
    `agent` span is stored. Results are cached per trace id, so the three evaluators below make
    one query per case.
    """

    def __init__(self, client, wait_seconds: float = 30, poll_seconds: float = 2):
        self.client = client
        self.wait_seconds = wait_seconds
        self.poll_seconds = poll_seconds
        self._cache: dict[str, dict] = {}

    def __call__(self, trace_id: str) -> dict:
        if trace_id not in self._cache:
            self._cache[trace_id] = self._fetch(trace_id)
        return self._cache[trace_id]

    def _fetch(self, trace_id: str) -> dict:
        deadline = time.monotonic() + self.wait_seconds
        while True:
            spans = self.client.spans.get_spans(project_identifier=TRACE_PROJECT, trace_ids=[trace_id],
                                                limit=1000)
            if any(s["name"] == "agent" for s in spans) or time.monotonic() > deadline:
                return summarize(spans)
            time.sleep(self.poll_seconds)


def summarize(spans: list[dict]) -> dict:
    llm = [s["attributes"] for s in spans if s.get("span_kind") == "LLM"]
    agent = next((s["attributes"] for s in spans if s["name"] == "agent"), {})
    return {
        "cost_usd": sum(a.get("llm.cost.total", 0) for a in llm),
        "tokens": sum(a.get("llm.token_count.total", 0) for a in llm),
        "llm_calls": len(llm),
        "models": sorted({a["llm.model_name"] for a in llm if "llm.model_name" in a}),
        "termination_reason": agent.get("agent.termination_reason", "unknown"),
        # Every note any search returned, and the notes that went into the answer's context.
        "retrieved": sorted({p for s in spans if s["name"] == "retrieve"
                             for p in s["attributes"].get("search.note_paths", [])}),
        "in_context": sorted(agent.get("agent.note_paths", [])),
    }


def usage_evaluators(usage: TraceUsage) -> dict:
    """`cost_usd`, `tokens` and `llm_calls` per case, as named evaluators."""
    return {
        "cost_usd": lambda output: usage(output["trace_id"])["cost_usd"],
        "tokens": lambda output: usage(output["trace_id"])["tokens"],
        "llm_calls": lambda output: usage(output["trace_id"])["llm_calls"],
    }


def found(paths: list[str], expected: dict) -> bool:
    """Note questions: an expected note is in `paths`. Other questions: `paths` is empty."""
    if not expected["notes"]:
        return not paths
    return bool(set(paths) & set(expected["notes"]))


def trace_evaluators(usage: TraceUsage) -> dict:
    """The retrieval path and the ending of each case, read from its trace.

    `judged` is false when the judge failed and the answer was accepted unjudged
    (`judge_unavailable`): such a case is not a real pass, so its scores are reported apart.
    """
    return {
        # Off-topic questions may still search; only notes reaching the context count against them.
        "note_retrieved": lambda output, expected: (
            found(usage(output["trace_id"])["retrieved"], expected) if expected["notes"] else True),
        "note_in_context": lambda output, expected: found(usage(output["trace_id"])["in_context"], expected),
        "judged": lambda output: usage(output["trace_id"])["termination_reason"] != "judge_unavailable",
    }


def failed_checks(output: dict, expected: dict, trace: dict) -> list[str]:
    """Names of the checks one case failed, for `--strict`: every expected word in the answer, an
    expected note retrieved, in context and cited, and the answer judged. `trace` is a
    `summarize` result."""
    checks = {
        "expected_words": expected_words(output, expected) == 1,
        "note_retrieved": found(trace["retrieved"], expected) if expected["notes"] else True,
        "note_in_context": found(trace["in_context"], expected),
        "note_cited": note_cited(output, expected),
        "judged": trace["termination_reason"] != "judge_unavailable",
    }
    return [name for name, ok in checks.items() if not ok]
