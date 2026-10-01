from pathlib import Path

import pytest
from common.collection import Collection

from search.vault import read_vault, to_text


def test_to_text_strips_frontmatter_and_wikilinks():
    raw = "---\ntags: [rag]\n---\nSee [[Embeddings]], [[Vector DB|pgvector]], [[RAG#Chunking]] and ![[img.png]]."
    assert to_text("Note", raw) == "Note\n\nSee Embeddings, pgvector, RAG and img.png."


def test_read_vault_skips_hidden_and_ignored(tmp_path):
    (tmp_path / "ml" / "rag").mkdir(parents=True)
    (tmp_path / "ml" / "rag" / "a.md").write_text("alpha")
    (tmp_path / "ml" / ".obsidian").mkdir()
    (tmp_path / "ml" / ".obsidian" / "x.md").write_text("config")
    (tmp_path / "ml" / "CLAUDE.md").write_text("instructions")
    notes = read_vault(tmp_path, ["ml"])
    assert [n.path for n in notes] == ["ml/rag/a.md"]
    assert notes[0].text == "a\n\nalpha"


def test_read_vault_reads_only_the_collection_folders(tmp_path):
    for folder in ("ml", "test", "finance"):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / "n.md").write_text(folder)
    assert [n.path for n in read_vault(tmp_path, ["ml", "test"])] == ["ml/n.md", "test/n.md"]


def test_missing_collection_folder_stops_sync_instead_of_deleting_everything(tmp_path):
    (tmp_path / "ml").mkdir()
    with pytest.raises(SystemExit, match="does not exist"):
        read_vault(tmp_path, ["ml", "test"])


def test_vault_path_expands_home(monkeypatch):
    from search.config import vault_path

    monkeypatch.setenv("SEARCH_VAULT_PATH", "$HOME/notes")
    assert vault_path() == Path.home() / "notes"
    monkeypatch.delenv("SEARCH_VAULT_PATH")
    assert vault_path() == Path.home() / "Documents/obsidian_git/Personal/knowledge_database"


def test_collections_default_to_every_collection_and_reject_unknown(monkeypatch):
    from search.config import collections

    monkeypatch.delenv("SEARCH_COLLECTIONS", raising=False)
    assert collections() == list(Collection)
    monkeypatch.setenv("SEARCH_COLLECTIONS", "ml")
    assert collections() == [Collection.ML]
    monkeypatch.setenv("SEARCH_COLLECTIONS", "ml,finance")
    with pytest.raises(SystemExit):
        collections()
