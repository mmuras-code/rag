"""The agent as a LangGraph graph (diagram: ../../graph.md, written by `python -m agent.graph`).

- decide (Plan): the LLM routes the question to one note collection (common.collection.Collection,
  described in COLLECTIONS: `ml`, or `test` for questions marked as test questions) or to none,
  and writes the search query. On a retry it also sees the judge's feedback, the queries already tried and the
  notes already found, and may write a new query to find what is missing.
- retrieve: hybrid search over the routed collection's notes (the search service, through the gRPC client generated
  from proto/: contracts.search.SearchClient); notes below MIN_SIMILARITY, a
  floor that only drops clear junk, are discarded. A query already tried is not searched again.
- grade: the LLM reads the question and an excerpt of each remaining note and keeps only the notes
  that help answer it. An unparseable reply keeps them all. Kept notes join the context.
- generate: the LLM answers, with the notes if any, told the judge's requirements (e.g. the word
  limit) up front. If the notes were searched and nothing relevant was found, it is told so, and
  says so in the answer. On a retry the request also holds each earlier answer (as an assistant
  turn) and the judge's feedback on it (as a user turn), from `State.context`.
- judge: a pluggable judge (agent/judges/: the LLM rubric judge or the 100-word limit, picked by
  AGENT_JUDGE) scores the answer 0-100. Above PASS_SCORE ends the run; otherwise back to decide,
  until MAX_GENERATIONS answers have been written. The best-scored answer is returned.
  A judge that fails (unparseable reply, or OpenRouter down) is logged and the answer accepted;
  the run then ends as `judge_unavailable`.

The LLM is any `chat(messages) -> str`; by default `llm.OpenRouterClient` (Haiku). The LLM judge
uses its own model (AGENT_JUDGE_MODEL, see judges/). Run `python -m agent.graph` to write the graph
as Mermaid to ../graph.md.

Tracing (observability/, sent to Phoenix): `run` opens the `agent` root span; LangChain
instrumentation adds a span per graph node, and the nodes add the attributes from
../../docs/telemetry.md to their own span.

Metrics (observability/, sent to Grafana): `run` is the `agent.run` operation and each search the
`agent.search` operation (count, latency, outcome); model calls are `llm.chat` (../llm/). Each
graph node's run time is `ml.time` with `function` = `agent.<node>` (`@timed`).
Search being unreachable or answering an error is a modelled failure (`SearchUnavailable`).

The graph is served as the `agent.v1.Agent` gRPC service by server.py.
"""

import functools
import json
import os
import re
from pathlib import Path
from typing import TypedDict

import grpc
from common.collection import Collection
from common.log import get_logger
from contracts.interceptors import Retry
from contracts.search import SearchClient
from contracts.search.v1.search_pb2 import Result
from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from llm import OpenRouterClient
from llm.openrouter import OpenRouterError
from observability import ServiceFault, operation, timed, tracer
from openinference.instrumentation.langchain import get_current_span as node_span
from openinference.semconv.trace import OpenInferenceSpanKindValues, SpanAttributes
from opentelemetry import trace

from agent.judges import Judge, make_judge
from agent.judges.requirements import requirements_prompt

log = get_logger("agent")
_tracer = tracer("agent")

PASS_SCORE = 50  # the judge's score must be above this to finish
MAX_GENERATIONS = 3  # hard cap on answers written per request
SEARCH_K = 5
SEARCH_ATTEMPTS = 3  # a search that fails UNAVAILABLE is retried, with backoff, up to this many tries in all
# Cosine similarity below which a search result is junk and dropped before grading. Not a relevance
# test: with openai/text-embedding-3-small the right note scores 0.22-0.59 and wrong-but-close
# notes overlap that range, so no cutoff separates them (the grade step does that). Queries the
# notes cannot answer at all keep every result at or below 0.15. Measured with
# `just eval retrieval` (eval/datasets/retrieval.jsonl); re-run it after changing the embedding model.
MIN_SIMILARITY = float(os.environ.get("AGENT_MIN_SIMILARITY", "0.2"))
GRADE_EXCERPT_CHARS = 1500  # how much of each note the grade step reads

# What each collection holds, for the routing prompt. Every Collection must be described.
COLLECTIONS = {
    Collection.ML: "the user's notes on machine learning (RAG, diffusion, agents, MCP, LLMOps, NLP, "
                   "PyTorch, ML career and certification plans, and similar).",
    Collection.TEST: "made-up facts about the user, used for testing. Pick it only when the message "
                     "says it is a test question (e.g. \"Test question: what is my favorite number?\"); "
                     "never for an ordinary question.",
}
NO_ROUTE = "none"

DECIDE_PROMPT = """You route questions for an assistant that can search the user's notes. The notes \
are in these collections:

""" + "\n".join(f'- "{c}": {d}' for c, d in COLLECTIONS.items()) + f"""

Pick the one collection that may help answer the last user message, or "{NO_ROUTE}" when no notes \
are needed: greetings, small talk, and questions that match no collection.

Reply with JSON only: {{"route": {" or ".join(f'"{c}"' for c in [*COLLECTIONS, NO_ROUTE])}, \
"query": "search query if a collection is picked, else empty"}}"""

RETRY_DECIDE_PROMPT = """

## Retry

An answer to this conversation was rejected. The judge's feedback:
{feedback}

Queries already searched: {queries}
Notes already found: {paths}

If the feedback says information is missing that the notes may hold, set route to the collection \
that may hold it and write a different query aimed at what is missing. Otherwise set route to \
"none": the answer will be rewritten with the notes already found."""

GRADE_PROMPT = """You check search results for an assistant. Given a QUESTION and excerpts of \
notes from the user's knowledge base, list the notes that contain information useful for \
answering the question. A note on a nearby topic that does not help answer this question is \
not relevant.

Reply with JSON only: {"relevant": ["path", ...]} (an empty list if none is relevant)"""

ANSWER_PROMPT = "You are a helpful assistant."

NOTES_PROMPT = """Below are notes from the user's knowledge base that are relevant to the question. \
Use them, and cite the paths of the notes you used as [path]. If they do not fully answer the \
question, say what is missing and answer the rest from general knowledge."""

NO_NOTES_PROMPT = """The user's notes were searched and none is relevant to this question. Say so \
in one short sentence, then answer from general knowledge. Do not cite any notes."""

# What the judge sees in place of notes when the search found nothing relevant, so it does not
# mark down the sentence NO_NOTES_PROMPT asks for.
NO_NOTES_FOR_JUDGE = """(The user's notes were searched and none was relevant. The assistant was told \
to say so in one short sentence, then answer from general knowledge. That sentence is correct, \
not filler.)"""

RETRY_PROMPT = """Your previous answer was rejected. Feedback:
{feedback}

Write a new, complete answer to my question that fixes this. Reply with the answer only."""


class SearchUnavailable(ServiceFault):
    """The search service could not be reached or answered with an error."""


class State(TypedDict, total=False):
    messages: list[dict]  # the conversation from Open WebUI, OpenAI-style
    question: str  # text of the last user message
    needs_notes: bool  # decide's latest call: search (again)
    collection: str  # the collection decide routed to; "" searches every collection
    query: str  # search query written by decide
    queries: list[str]  # every query searched, in order
    candidates: list[Result]  # the latest search's results above MIN_SIMILARITY, for grade
    notes: list[Result]  # relevant notes from every search, deduplicated; empty if none
    answer: str  # latest answer
    score: int  # judge score of the latest answer
    feedback: str  # judge feedback on the latest answer
    context: list[AIMessage]  # earlier answers and the judge's feedback on each, in order
    attempts: int  # answers written so far (not `generations`: OpenInference reads that key as LLM output)
    best_answer: str
    best_score: int
    judge_unavailable: bool  # the last judge call failed, so its answer was accepted unjudged


def _text(content: str | list) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")


def parse_json(reply: str) -> dict:
    """The first JSON object in an LLM reply (models sometimes wrap it in prose or a code fence)."""
    match = re.search(r"\{.*\}", reply, re.DOTALL)
    if not match:
        raise ValueError(f"no JSON object in reply: {reply[:200]!r}")
    return json.loads(match.group(0))


def notes_context(notes: list[Result]) -> str:
    return "\n\n".join(f'<note path="{n.path}">\n{n.content}\n</note>' for n in notes)


def transcript(messages: list[dict]) -> str:
    return "\n\n".join(f"{m['role']}: {_text(m['content'])}" for m in messages if m["role"] != "system")


def traced(node):
    """Make the node's span (created by the LangChain instrumentation) the current span while the
    node runs, so its attributes and the LLM spans inside it land on that node, not the root."""

    @functools.wraps(node)
    def wrapper(state):
        span = node_span()
        if span is None:
            return node(state)
        with trace.use_span(span, end_on_exit=False):
            return node(state)

    return wrapper


def build_graph(chat=None, search: SearchClient | None = None, judge: Judge | None = None):
    """`chat` routes, grades and answers (default: `OpenRouterClient`, LLM_OPENROUTER_MODEL); `judge`
    scores (default: the one AGENT_JUDGE names, see agent/judges/)."""
    chat = chat or OpenRouterClient().chat
    # A search query is read-only, so it is safe to repeat: ride out a search restart.
    search = search or SearchClient(interceptors=[Retry(max_attempts=SEARCH_ATTEMPTS)])
    judge_client = judge or make_judge()

    @timed("agent.decide")
    def decide(state: State) -> dict:
        question = next((_text(m["content"]) for m in reversed(state["messages"]) if m["role"] == "user"), "")
        if not question.strip():
            return {"question": question, "needs_notes": False, "collection": "", "query": ""}
        prompt = DECIDE_PROMPT
        if state.get("feedback"):
            prompt += RETRY_DECIDE_PROMPT.format(
                feedback=state["feedback"], queries=json.dumps(state.get("queries", [])),
                paths=json.dumps([n.path for n in state.get("notes", [])]))
        reply = chat([{"role": "system", "content": prompt},
                      {"role": "user", "content": transcript(state["messages"])}])
        try:
            d = parse_json(reply)
            route, query = str(d.get("route")), str(d.get("query") or question)
            if route != NO_ROUTE:
                Collection(route)  # ValueError for an unknown route
        except ValueError:
            # Unparseable or unknown route: search every collection. Grading drops irrelevant notes.
            log.warning("decide: unparseable reply, searching every collection: %r", reply[:200])
            route, query = "", question
        needs = route != NO_ROUTE
        collection = route if needs else ""
        log.info("decide: route=%s query=%r", route or "all", query)
        trace.get_current_span().set_attributes({"agent.needs_notes": needs, "agent.route": route or "all",
                                                 "search.query": query if needs else ""})
        return {"question": question, "needs_notes": needs, "collection": collection, "query": query}

    @timed("agent.retrieve")
    def retrieve(state: State) -> dict:
        with operation("agent.search"):
            try:
                results = search.query(state["query"], k=SEARCH_K, collection=state.get("collection", ""))
            except grpc.RpcError as e:
                raise SearchUnavailable(f"search failed: {e.code().name}: {e.details()}") from e
        candidates = [r for r in results if r.similarity >= MIN_SIMILARITY]
        similarities = [round(r.similarity, 3) for r in results]
        log.info("retrieve: %d results, %d above %.2f; similarities %s", len(results), len(candidates),
                 MIN_SIMILARITY, similarities)
        trace.get_current_span().set_attributes({
            "search.query": state["query"],
            "search.collection": state.get("collection", ""),
            "search.note_paths": [r.path for r in results],
            # Every result's similarity, kept or not: the data for checking MIN_SIMILARITY.
            "search.similarities": similarities,
            "search.kept": len(candidates),
            "search.dropped": len(results) - len(candidates),
        })
        return {"candidates": candidates, "queries": [*state.get("queries", []), state["query"]]}

    @timed("agent.grade")
    def grade(state: State) -> dict:
        candidates = state.get("candidates", [])
        relevant = candidates
        if candidates:
            excerpts = "\n\n".join(f'<note path="{n.path}">\n{n.content[:GRADE_EXCERPT_CHARS]}\n</note>'
                                   for n in candidates)
            reply = chat([{"role": "system", "content": GRADE_PROMPT},
                          {"role": "user", "content": f"QUESTION:\n{state['question']}\n\nNOTES:\n{excerpts}"}])
            try:
                paths = set(parse_json(reply)["relevant"])
                relevant = [n for n in candidates if n.path in paths]
            except (ValueError, KeyError, TypeError):
                # Keep every candidate rather than answer without notes that may be relevant.
                log.warning("grade: unparseable reply, keeping all %d notes: %r", len(candidates), reply[:200])
        log.info("grade: %d of %d relevant: %s", len(relevant), len(candidates), [n.path for n in relevant])
        trace.get_current_span().set_attributes({
            "grade.relevant_paths": [n.path for n in relevant],
            "grade.rejected_paths": [n.path for n in candidates if n not in relevant],
        })
        seen = {n.path for n in state.get("notes", [])}
        return {"notes": [*state.get("notes", []), *(n for n in relevant if n.path not in seen)]}

    @timed("agent.generate")
    def generate(state: State) -> dict:
        system = "\n\n".join(filter(None, [ANSWER_PROMPT, requirements_prompt(judge_client.requirements)]))
        if state.get("notes"):
            system += "\n\n" + NOTES_PROMPT + "\n\n" + notes_context(state["notes"])
        elif state.get("queries"):
            system += "\n\n" + NO_NOTES_PROMPT
        rest = [m for m in state["messages"] if m["role"] != "system"]
        # Earlier answers go back as assistant turns, the judge's feedback as user turns, so the
        # request always ends on a user message (a trailing assistant turn is a prefill).
        context = [{"role": "user", "content": RETRY_PROMPT.format(feedback=m.content)} if m.name == "judge"
                   else {"role": "assistant", "content": m.content} for m in state.get("context", [])]
        generation = state.get("attempts", 0) + 1
        trace.get_current_span().set_attribute("agent.iteration", generation)
        answer = chat([{"role": "system", "content": system}, *rest, *context])
        return {"answer": answer, "attempts": generation}

    @timed("agent.judge")
    def judge(state: State) -> dict:
        try:
            notes = notes_context(state.get("notes", [])) or (NO_NOTES_FOR_JUDGE if state.get("queries") else "")
            v = judge_client.score(state["question"], state["answer"], notes)
            score, feedback = v.score, v.feedback
        except (ValueError, KeyError, TypeError, OpenRouterError) as e:
            # A crashed or unreachable verifier is logged and skipped, not turned into feedback
            # (docs/architecture.md); the run ends as `judge_unavailable`, not `passed`.
            log.warning("judge: failed, accepting the answer unjudged: %s", e)
            score, feedback = PASS_SCORE + 1, ""
            failed = True
        else:
            failed = False
        log.info("judge: generation %d scored %d %s", state["attempts"], score, feedback)
        trace.get_current_span().set_attributes({
            "agent.iteration": state["attempts"],
            "verifier.name": type(judge_client).__name__,
            "verifier.score": score,
            "verifier.passed": score > PASS_SCORE,
            "verifier.blocking": score <= PASS_SCORE,
            "verifier.feedback": feedback,
        })
        update = {"score": score, "feedback": feedback, "judge_unavailable": failed}
        if feedback:
            update["context"] = [*state.get("context", []), AIMessage(state["answer"]),
                                 AIMessage(feedback, name="judge")]
        if score > state.get("best_score", -1):
            update |= {"best_answer": state["answer"], "best_score": score}
        return update

    def after_decide(state: State) -> str:
        # A query already searched would return the same notes: rewrite with what is there.
        if state["needs_notes"] and state["query"] not in state.get("queries", []):
            return "retrieve"
        return "generate"

    def after_judge(state: State) -> str:
        if state["score"] > PASS_SCORE or state["attempts"] >= MAX_GENERATIONS:
            return END
        return "decide"

    g = StateGraph(State)
    g.add_node("decide", traced(decide))
    g.add_node("retrieve", traced(retrieve))
    g.add_node("grade", traced(grade))
    g.add_node("generate", traced(generate))
    g.add_node("judge", traced(judge))
    g.add_edge(START, "decide")
    g.add_conditional_edges("decide", after_decide, ["retrieve", "generate"])
    g.add_edge("retrieve", "grade")
    g.add_edge("grade", "generate")
    g.add_edge("generate", "judge")
    g.add_conditional_edges("judge", after_judge, ["decide", END])
    return g.compile()


def run(messages: list[dict], graph=None) -> str:
    """Answer a conversation. Returns the best-scored answer. Traced as the `agent` root span."""
    kind = OpenInferenceSpanKindValues.AGENT.value
    with (_tracer.start_as_current_span("agent", attributes={SpanAttributes.OPENINFERENCE_SPAN_KIND: kind}) as span,
          operation("agent.run")):
        span.set_attribute(SpanAttributes.INPUT_VALUE, transcript(messages))
        state = (graph or build_graph()).invoke({"messages": messages})
        answer = state.get("best_answer") or state.get("answer", "")
        passed = state.get("score", PASS_SCORE + 1) > PASS_SCORE
        reason = "judge_unavailable" if state.get("judge_unavailable") else "passed" if passed else "iteration_limit"
        searched = bool(state.get("queries"))
        span.set_attributes({
            SpanAttributes.OUTPUT_VALUE: answer,
            "agent.iterations": state.get("attempts", 0),
            "agent.retrieval_skipped": not searched,
            "agent.retrieval_empty": searched and not state.get("notes"),
            "agent.searches": len(state.get("queries", [])),
            "agent.note_paths": [n.path for n in state.get("notes", [])],
            "agent.termination_reason": reason,
        })
        return answer


if __name__ == "__main__":
    from unittest.mock import MagicMock

    out = Path(__file__).resolve().parents[2] / "graph.md"
    mermaid = build_graph(chat=lambda m: "", judge=MagicMock()).get_graph().draw_mermaid()
    out.write_text(f"# Agent graph\n\nGenerated by `python -m agent.graph`.\n\n```mermaid\n{mermaid}```\n")
    print(f"wrote {out}")
