"""Read Obsidian notes into the text that gets embedded. The vault is never written."""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

# Vault files that are instructions, not notes.
IGNORED_NAMES = {"CLAUDE.md"}

FRONTMATTER = re.compile(r"\A---\n.*?\n---[ \t]*\n?", re.DOTALL)
# [[target]], [[target#heading]], [[target|alias]], ![[embed]]
WIKILINK = re.compile(r"!?\[\[([^\]|#]*)(?:#[^\]|]*)?(?:\|([^\]]*))?\]\]")


@dataclass
class Note:
    path: str
    text: str
    content_hash: str


def to_text(title: str, raw: str) -> str:
    body = FRONTMATTER.sub("", raw)
    body = WIKILINK.sub(lambda m: m.group(2) or m.group(1), body)
    return f"{title}\n\n{body.strip()}"


def read_vault(root: Path, collections: list[str]) -> list[Note]:
    """Every note in the `collections` folders of `root`; paths are relative to `root`, so each
    starts with its collection. A missing collection folder is an error, not an empty collection:
    syncing it as empty would delete every stored note in it."""
    notes = []
    for collection in collections:
        folder = root / collection
        if not folder.is_dir():
            raise SystemExit(f"collection folder {folder} does not exist (SEARCH_VAULT_PATH is the vault "
                             f"root that holds the collection folders)")
        for file in sorted(folder.rglob("*.md")):
            rel = file.relative_to(root)
            if any(part.startswith(".") for part in rel.parts) or file.name in IGNORED_NAMES:
                continue
            text = to_text(file.stem, file.read_text(encoding="utf-8"))
            notes.append(Note(str(rel), text, hashlib.sha256(text.encode()).hexdigest()))
    return notes
