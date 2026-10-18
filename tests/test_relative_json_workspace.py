"""Relative/symlink roots remain usable with locked staged JSON writes."""
from pathlib import Path

from threaddesk.api.service import ThreadService
from threaddesk.storage.json_store import JsonStore


def test_relative_root_supports_repeated_whiteboard_and_restart(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    svc = ThreadService(JsonStore(Path("relative-workspace")))
    thread = svc.create("Synthetic relative workspace")
    for number in range(3):
        svc.append_whiteboard(thread.id, actor="Synthetic", actor_type="system",
                              entry_type="progress", content=f"Entry {number}")
    reopened = ThreadService(JsonStore(Path("relative-workspace")))
    assert len(reopened.store.list_whiteboard(thread.id)) == 3
    assert reopened.get(thread.id).id == thread.id
    assert reopened.store.root == (tmp_path / "relative-workspace").resolve()


def test_new_node_can_be_referenced_inside_same_atomic_write(tmp_path):
    svc = ThreadService(JsonStore(tmp_path))
    existing = svc.create_node("decision", "Earlier", status="confirmed")
    with svc.store.transaction():
        new = svc.create_node("decision", "Replacement", status="confirmed")
        svc.connect(new.id, existing.id, "follows")
    assert svc.get_node(new.id).title == "Replacement"
    assert svc.list_relations()[0].source_id == new.id
