"""The notes table in pgvector."""

import psycopg
from pgvector.psycopg import register_vector

SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    path         text PRIMARY KEY,
    content_hash text NOT NULL,
    content      text NOT NULL,
    embedding    vector NOT NULL,
    model        text NOT NULL,
    token_count  integer NOT NULL,
    truncated    boolean NOT NULL,
    updated_at   timestamptz NOT NULL DEFAULT now()
)
"""


def connect(url: str) -> psycopg.Connection:
    conn = psycopg.connect(url, autocommit=True)
    conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    register_vector(conn)
    conn.execute(SCHEMA)
    return conn


def stored(conn) -> dict[str, tuple[str, str]]:
    """path -> (content_hash, model)"""
    return {p: (h, m) for p, h, m in conn.execute("SELECT path, content_hash, model FROM notes")}


def upsert(conn, path, content_hash, content, vector, model, token_count, truncated) -> None:
    conn.execute(
        """
        INSERT INTO notes (path, content_hash, content, embedding, model, token_count, truncated)
        VALUES (%s, %s, %s, %s::vector, %s, %s, %s)
        ON CONFLICT (path) DO UPDATE SET
            content_hash = EXCLUDED.content_hash, content = EXCLUDED.content,
            embedding = EXCLUDED.embedding, model = EXCLUDED.model,
            token_count = EXCLUDED.token_count, truncated = EXCLUDED.truncated, updated_at = now()
        """,
        (path, content_hash, content, str(vector), model, token_count, truncated),
    )


def delete(conn, paths: list[str]) -> None:
    conn.execute("DELETE FROM notes WHERE path = ANY(%s)", (paths,))


def notes(conn, vector: list[float], model: str, collection: str = "") -> list[tuple[str, float, str]]:
    """Every note for `model` with its cosine similarity to `vector`: (path, similarity, content),
    most similar first. `collection` keeps only the notes under that folder; empty keeps all.
    Exact search over all rows; the vault is small."""
    return conn.execute(
        """
        SELECT path, 1 - (embedding <=> %(v)s::vector) AS similarity, content
        FROM notes WHERE model = %(m)s AND (%(c)s = '' OR starts_with(path, %(c)s || '/'))
        ORDER BY embedding <=> %(v)s::vector
        """,
        {"v": str(vector), "m": model, "c": collection},
    ).fetchall()
