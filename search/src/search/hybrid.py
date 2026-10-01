"""Reciprocal rank fusion of several rankings."""

RRF_K = 60


def rrf(rankings: list[list[str]], k: int = RRF_K) -> list[tuple[str, float]]:
    """Fuse ranked lists of paths: score(path) = sum over lists of 1 / (k + rank), rank from 1."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, path in enumerate(ranking, start=1):
            scores[path] = scores.get(path, 0.0) + 1 / (k + rank)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)
