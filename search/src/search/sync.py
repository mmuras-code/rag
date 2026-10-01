"""Incremental sync: embed new or changed notes, delete rows for removed notes."""


import httpx
from common.log import get_logger
from llm import embed
from llm.openrouter import OpenRouterError
from observability import operation

from search import config, store
from search.vault import Note, read_vault

log = get_logger("search.sync")


def plan(notes: list[Note], stored: dict[str, tuple[str, str]], model: str) -> tuple[list[Note], list[str]]:
    """Which notes to embed and which paths to delete. A model change re-embeds everything."""
    to_embed = [n for n in notes if stored.get(n.path) != (n.content_hash, model)]
    current = {n.path for n in notes}
    return to_embed, sorted(p for p in stored if p not in current)


def sync(conn) -> None:
    """Measured as the `search.sync` operation; a note that fails to embed is logged, not raised."""
    with operation("search.sync"):
        _sync(conn)


def _sync(conn) -> None:
    notes = read_vault(config.vault_path(), config.collections())
    to_embed, to_delete = plan(notes, store.stored(conn), config.EMBED_MODEL)
    log.info("%d notes in vault, %d to embed, %d to delete", len(notes), len(to_embed), len(to_delete))
    failed = 0
    for note in to_embed:
        try:
            e = embed(note.text, model=config.EMBED_MODEL)
        except (OpenRouterError, httpx.HTTPError) as err:
            # Not stored, so the next sync retries it. One bad note must not stop the server starting.
            failed += 1
            log.warning("failed to embed %s, skipped: %s", note.path, err)
            continue
        store.upsert(conn, note.path, note.content_hash, note.text, e.vector, config.EMBED_MODEL,
                     e.token_count, e.truncated)
        log.info("embedded %s (%d tokens)%s", note.path, e.token_count, " TRUNCATED" if e.truncated else "")
    if to_delete:
        store.delete(conn, to_delete)
        log.info("deleted %s", ", ".join(to_delete))
    log.info("sync done: %d embedded, %d failed, %d deleted", len(to_embed) - failed, failed, len(to_delete))
