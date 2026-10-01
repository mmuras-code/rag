"""Okapi BM25 over the stored notes, computed in Python at query time.

Postgres full-text ranking (ts_rank) is not BM25, and the pgvector image has no BM25 extension.
The vault is small (about a hundred notes), so building the index per query is cheap.
"""

import math
import re
from collections import Counter

TOKEN = re.compile(r"\w+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    return TOKEN.findall(text.lower())


def rank(docs: dict[str, str], query: str, k1: float = 1.5, b: float = 0.75) -> list[tuple[str, float]]:
    """Paths with a positive BM25 score for `query`, best first."""
    if not docs:
        return []
    tfs = {path: Counter(tokenize(text)) for path, text in docs.items()}
    lengths = {path: sum(tf.values()) for path, tf in tfs.items()}
    avg_len = sum(lengths.values()) / len(lengths) or 1
    df = Counter(term for tf in tfs.values() for term in tf)
    n = len(docs)
    terms = set(tokenize(query))
    scores = {}
    for path, tf in tfs.items():
        score = 0.0
        for term in terms & tf.keys():
            idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
            f = tf[term]
            score += idf * f * (k1 + 1) / (f + k1 * (1 - b + b * lengths[path] / avg_len))
        if score > 0:
            scores[path] = score
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)
