"""Retrieval eval: search alone, no LLM. Shows whether search finds the right notes.

    uv run python -m evals.retrieval [--dataset datasets/retrieval.jsonl] [--k 5] [--min-similarity 0.2]

Each case in the dataset is `query` plus `expected` (vault paths that answer it; empty for a query
the notes cannot answer). Every query goes to the running search service through `SearchClient`
(gRPC, from `contracts`), and the run prints per case and on average:

- recall@k: share of the expected notes in the top k.
- MRR: 1 / rank of the first expected note (0 when none is in the top k).
- kept: share of the expected notes whose cosine similarity clears `--min-similarity`, the floor
  the agent drops notes under (AGENT_MIN_SIMILARITY). For a query with no expected notes, 1 when
  every result is below it.
- the similarity of each expected note, the data for setting that floor.

Free and deterministic: it embeds each query once (OpenRouter embeddings) and calls no chat model.
"""

import argparse
import os
import statistics
from dataclasses import dataclass
from pathlib import Path

from contracts.search import SearchClient
from contracts.search.v1.search_pb2 import Result

from evals import dataset

DEFAULT_MIN_SIMILARITY = float(os.environ.get("AGENT_MIN_SIMILARITY", "0.2"))


@dataclass
class CaseScore:
    query: str
    expected: list[str]
    recall: float
    mrr: float
    kept: float
    expected_similarity: dict[str, float | None]  # None: not in the results
    top: list[tuple[str, float]]  # (path, similarity) of the results, best first


def score(query: str, expected: list[str], results: list[Result], k: int, min_similarity: float) -> CaseScore:
    paths = [r.path for r in results[:k]]
    similarity = {r.path: r.similarity for r in results}
    if expected:
        recall = sum(p in paths for p in expected) / len(expected)
        rank = next((i for i, p in enumerate(paths, start=1) if p in expected), None)
        mrr = 1 / rank if rank else 0.0
        kept = sum(similarity.get(p, -1) >= min_similarity for p in expected) / len(expected)
    else:
        # Nothing to find: recall and MRR do not apply; kept means the floor dropped everything.
        recall = mrr = 1.0
        kept = float(all(r.similarity < min_similarity for r in results[:k]))
    return CaseScore(query, expected, recall, mrr, kept, {p: similarity.get(p) for p in expected},
                     [(r.path, r.similarity) for r in results[:k]])


def report(scores: list[CaseScore], k: int, min_similarity: float) -> str:
    lines = [f"{'recall':>6} {'MRR':>5} {'kept':>5}  query → expected (similarity)"]
    for s in scores:
        flag = "" if s.recall == 1 and s.kept == 1 else "  <-- miss"
        if s.expected:
            sims = ", ".join(f"{p} ({'missing' if v is None else f'{v:.3f}'})"
                             for p, v in s.expected_similarity.items())
        else:
            sims = "(none expected) top: " + ", ".join(f"{p} ({v:.3f})" for p, v in s.top[:2])
        lines.append(f"{s.recall:6.2f} {s.mrr:5.2f} {s.kept:5.2f}  {s.query!r} → {sims}{flag}")
    on_topic = [s for s in scores if s.expected]
    off_topic = [s for s in scores if not s.expected]
    lines.append("")
    if on_topic:
        lines.append(f"{len(on_topic)} on-topic queries: recall@{k} {statistics.mean(s.recall for s in on_topic):.2f}, "
                     f"MRR {statistics.mean(s.mrr for s in on_topic):.2f}, "
                     f"kept at {min_similarity} {statistics.mean(s.kept for s in on_topic):.2f}")
        found = [v for s in on_topic for v in s.expected_similarity.values() if v is not None]
        if found:
            lines.append(f"  similarity of expected notes: min {min(found):.3f}, "
                         f"median {statistics.median(found):.3f}, max {max(found):.3f}")
    if off_topic:
        best = [s.top[0][1] for s in off_topic if s.top]
        lines.append(f"{len(off_topic)} off-topic queries: all dropped at {min_similarity} "
                     f"{statistics.mean(s.kept for s in off_topic):.2f}"
                     + (f", best similarity max {max(best):.3f}" if best else ""))
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", type=Path, default=dataset.DATASETS / "retrieval.jsonl")
    parser.add_argument("--k", type=int, default=5, help="results per query (the agent uses 5)")
    parser.add_argument("--min-similarity", type=float, default=DEFAULT_MIN_SIMILARITY,
                        help="the agent's floor (default: AGENT_MIN_SIMILARITY or 0.2)")
    args = parser.parse_args()

    search = SearchClient()
    scores = [score(c["query"], c["expected"], search.query(c["query"], k=args.k), args.k, args.min_similarity)
              for c in dataset.load(args.dataset)]
    print(report(scores, args.k, args.min_similarity))


if __name__ == "__main__":
    main()
