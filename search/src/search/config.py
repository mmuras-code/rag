import os
from pathlib import Path

from common.collection import Collection
from common.stage import load_env
from llm import DEFAULT_EMBED_MODEL

# search/.env, read in development only (see common/stage.py).
STAGE = load_env(Path(__file__).resolve().parents[2] / ".env")

DATABASE_URL = os.environ.get("SEARCH_DATABASE_URL", "postgresql://search:search@127.0.0.1:5433/search")
PORT = int(os.environ.get("SEARCH_PORT", "8001"))
EMBED_MODEL = os.environ.get("LLM_EMBED_MODEL", DEFAULT_EMBED_MODEL)


DEFAULT_VAULT = "~/Documents/obsidian_git/Personal/knowledge_database"


def vault_path() -> Path:
    """SEARCH_VAULT_PATH, the vault root that holds the collection folders, with ~ and $HOME
    expanded (.env files do not expand them)."""
    path = os.environ.get("SEARCH_VAULT_PATH", DEFAULT_VAULT)
    return Path(os.path.expandvars(path)).expanduser()


def collections() -> list[Collection]:
    """SEARCH_COLLECTIONS, comma-separated (default: every `Collection`): the top-level folders of
    the vault root that are indexed. Nothing outside them is read. An unknown name stops search."""
    names = [n.strip() for n in os.environ.get("SEARCH_COLLECTIONS", ",".join(Collection)).split(",") if n.strip()]
    try:
        return [Collection(n) for n in names]
    except ValueError:
        raise SystemExit(f"SEARCH_COLLECTIONS={names} must be names from {[c.value for c in Collection]}") from None
