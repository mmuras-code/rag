import pytest

from search import bm25
from search.hybrid import rrf


def test_rrf_uses_k_60_and_sums_lists():
    fused = dict(rrf([["a", "b"], ["b", "c"]]))
    assert fused["b"] == pytest.approx(1 / 62 + 1 / 61)
    assert fused["a"] == pytest.approx(1 / 61)
    assert fused["c"] == pytest.approx(1 / 62)
    assert [p for p, _ in rrf([["a", "b"], ["b", "c"]])] == ["b", "a", "c"]


def test_bm25_ranks_term_matches_and_drops_non_matches():
    docs = {"a": "rag retrieval augmented generation", "b": "diffusion models", "c": "rag rag rag"}
    ranked = bm25.rank(docs, "RAG")
    assert [p for p, _ in ranked] == ["c", "a"]


def test_bm25_rare_terms_weigh_more():
    docs = {"a": "common rare", "b": "common", "c": "common"}
    (top, _), *_ = bm25.rank(docs, "common rare")
    assert top == "a"


def test_bm25_empty():
    assert bm25.rank({}, "x") == []
