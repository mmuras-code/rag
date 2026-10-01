from contracts.search.v1.search_pb2 import Result

from evals.retrieval import report, score


def results(*pairs):
    return [Result(path=path, similarity=sim) for path, sim in pairs]


def test_expected_note_first_and_above_floor():
    s = score("q", ["a.md"], results(("a.md", 0.5), ("b.md", 0.3)), k=5, min_similarity=0.2)
    assert (s.recall, s.mrr, s.kept) == (1.0, 1.0, 1.0)
    assert s.expected_similarity == {"a.md": 0.5}


def test_rank_and_floor_are_scored_separately():
    s = score("q", ["a.md"], results(("b.md", 0.5), ("c.md", 0.4), ("a.md", 0.1)), k=5, min_similarity=0.2)
    assert s.recall == 1.0 and abs(s.mrr - 1 / 3) < 1e-9
    assert s.kept == 0.0  # found, then dropped by the floor


def test_note_outside_top_k_is_a_miss():
    s = score("q", ["a.md"], results(("b.md", 0.5), ("a.md", 0.4)), k=1, min_similarity=0.2)
    assert (s.recall, s.mrr) == (0.0, 0.0)


def test_recall_is_the_share_of_expected_notes_found():
    s = score("q", ["a.md", "z.md"], results(("a.md", 0.5)), k=5, min_similarity=0.2)
    assert s.recall == 0.5 and s.expected_similarity["z.md"] is None


def test_off_topic_query_passes_only_when_the_floor_drops_everything():
    assert score("q", [], results(("a.md", 0.1)), k=5, min_similarity=0.2).kept == 1.0
    assert score("q", [], results(("a.md", 0.3)), k=5, min_similarity=0.2).kept == 0.0


def test_report_flags_misses():
    s = score("q", ["a.md"], results(("b.md", 0.5)), k=5, min_similarity=0.2)
    assert "<-- miss" in report([s], k=5, min_similarity=0.2)
