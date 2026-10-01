import httpx
import pytest
from llm import Embedding
from llm.openrouter import OpenRouterError

from search import sync as sync_module
from search.sync import plan, sync
from search.vault import Note


def test_plan_embeds_new_changed_and_model_changes_and_deletes_removed():
    notes = [Note("same.md", "t", "h1"), Note("changed.md", "t", "h2"), Note("new.md", "t", "h3"),
             Note("old_model.md", "t", "h4")]
    stored = {"same.md": ("h1", "m"), "changed.md": ("old", "m"), "old_model.md": ("h4", "other"),
              "removed.md": ("h5", "m")}
    to_embed, to_delete = plan(notes, stored, "m")
    assert [n.path for n in to_embed] == ["changed.md", "new.md", "old_model.md"]
    assert to_delete == ["removed.md"]


def test_plan_unchanged_vault_embeds_nothing():
    notes = [Note("a.md", "t", "h")]
    assert plan(notes, {"a.md": ("h", "m")}, "m") == ([], [])


def test_sync_skips_notes_that_fail_to_embed(monkeypatch, caplog):
    notes = [Note("ok.md", "ok", "h1"), Note("api.md", "api", "h2"), Note("net.md", "net", "h3"),
             Note("ok2.md", "ok2", "h4")]
    errors = {"api": OpenRouterError("too many tokens"), "net": httpx.ConnectError("down")}

    def fake_embed(text, model):
        if text in errors:
            raise errors[text]
        return Embedding([0.1], 1, False)

    upserted = []
    monkeypatch.setattr(sync_module, "read_vault", lambda root, collections: notes)
    monkeypatch.setattr(sync_module, "embed", fake_embed)
    monkeypatch.setattr(sync_module.store, "stored", lambda conn: {})
    monkeypatch.setattr(sync_module.store, "upsert", lambda conn, path, *rest: upserted.append(path))
    with caplog.at_level("INFO", logger="search.sync"):
        sync(None)

    # Failed notes are not stored, so the next sync plans them again.
    assert upserted == ["ok.md", "ok2.md"]
    assert "2 embedded, 2 failed, 0 deleted" in caplog.text


def test_sync_does_not_swallow_bugs(monkeypatch):
    monkeypatch.setattr(sync_module, "read_vault", lambda root, collections: [Note("a.md", "a", "h")])
    monkeypatch.setattr(sync_module, "embed", lambda text, model: 1 / 0)
    monkeypatch.setattr(sync_module.store, "stored", lambda conn: {})
    with pytest.raises(ZeroDivisionError):
        sync(None)
