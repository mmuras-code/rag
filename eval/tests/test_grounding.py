"""grounding.jsonl and vault_facts.jsonl must stay true to the vault: each expected phrase is in the
case's note and in no other note, so an answer that contains it can only have come from that note.

Reads the vault (read-only) the way search does: the SEARCH_COLLECTIONS folders under the vault root
SEARCH_VAULT_PATH, no hidden paths, no CLAUDE.md. Skipped when the vault is absent.
"""

import os
from pathlib import Path

import pytest

from evals import dataset

VAULT = Path(os.path.expandvars(os.environ.get(
    "SEARCH_VAULT_PATH", "~/Documents/obsidian_git/Personal/knowledge_database"))).expanduser()
COLLECTIONS = [c.strip() for c in os.environ.get("SEARCH_COLLECTIONS", "ml,test").split(",") if c.strip()]
FILES = ["grounding.jsonl", "vault_facts.jsonl"]
CASES = [(name, case) for name in FILES for case in dataset.load(dataset.DATASETS / name)]

pytestmark = pytest.mark.skipif(not VAULT.is_dir(), reason=f"no vault at {VAULT}")


def notes() -> dict[str, str]:
    return {str(f.relative_to(VAULT)): f.read_text(encoding="utf-8").lower()
            for c in COLLECTIONS for f in (VAULT / c).rglob("*.md")
            if f.name != "CLAUDE.md" and not any(part.startswith(".") for part in f.relative_to(VAULT).parts)}


@pytest.mark.parametrize("name,case", CASES, ids=[f"{n}:{c['question'][:40]}" for n, c in CASES])
def test_expected_phrases_are_only_in_the_case_note(name, case):
    vault = notes()
    [note] = case["notes"]
    assert note in vault, f"{note} is not in the vault"
    for phrase in case["expect"]:
        holders = sorted(path for path, text in vault.items() if phrase.lower() in text)
        assert holders == [note], f"{phrase!r} is in {holders}, expected only {note}"


def test_vault_facts_use_different_notes():
    paths = [c["notes"][0] for n, c in CASES if n == "vault_facts.jsonl"]
    assert len(set(paths)) == len(paths)
