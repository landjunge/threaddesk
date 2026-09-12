from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.core.provenance import SourceRecord
from threaddesk.storage.json_migration import MigrationError, migrate_json_store
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore


def digest_tree(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


def seed(root: Path, size: int = 3) -> JsonStore:
    store = JsonStore(root)
    service = ThreadService(store)
    for index in range(size):
        thread = service.create(f"Thread {index}")
        service.set_note(f"Stand {index}")
        service.snapshot(f"Snapshot {index}", thread.id)
    project = service.create_node("project", "ThreadDesk", status="active")
    task = service.create_node("task", "SQLite", status="ready")
    service.connect(project.id, task.id, "contains")
    store.save_source_record(
        SourceRecord(
            "notion", "page-1", project.id, "a" * 64, "b" * 64,
            "export-1", "2026-09-12T20:00:00+00:00", "notion.v1.suggested_kind",
        )
    )
    return store


def canonical(store) -> dict:
    return {
        "threads": [item.to_dict() for item in store.list_threads(True)],
        "snapshots": {
            thread.id: [item.to_dict() for item in store.list_snapshots(thread.id)]
            for thread in store.list_threads(True)
        },
        "nodes": [item.to_dict() for item in store.list_nodes()],
        "relations": [item.to_dict() for item in store.list_relations()],
        "events": [item.to_dict() for item in store.list_graph_events()],
        "source_records": [item.to_dict() for item in store.list_source_records()],
        "current_id": store.get_current_id(),
    }


@pytest.mark.parametrize("size", [0, 3, 250], ids=["empty", "small", "large"])
def test_dry_run_and_import_preserve_json_and_match_canonical_state(tmp_path: Path, size: int) -> None:
    source = seed(tmp_path / "json", size)
    target = SQLiteStore(tmp_path / "sqlite")
    before = digest_tree(source.root)

    preview = migrate_json_store(source, target, dry_run=True)
    assert preview["changed"] is bool(size or source.list_nodes())
    assert canonical(target) == canonical(SQLiteStore(tmp_path / "empty"))

    result = migrate_json_store(source, target)
    assert result["status"] == "imported"
    assert canonical(target) == canonical(source)
    assert digest_tree(source.root) == before

    again = migrate_json_store(source, target)
    assert again["status"] == "noop"
    assert canonical(target) == canonical(source)


def test_corrupt_source_changes_neither_source_nor_sqlite(tmp_path: Path) -> None:
    source = seed(tmp_path / "json")
    (source.threads_dir / "broken.json").write_text('{"id":', encoding="utf-8")
    before = digest_tree(source.root)
    target = SQLiteStore(tmp_path / "sqlite")

    with pytest.raises(MigrationError):
        migrate_json_store(source, target)

    assert digest_tree(source.root) == before
    assert target.list_threads(True) == []


def test_interruption_rolls_back_the_whole_sqlite_transaction(tmp_path: Path) -> None:
    source = seed(tmp_path / "json", 10)
    target = SQLiteStore(tmp_path / "sqlite")

    def interrupt(stage: str) -> None:
        if stage == "after_threads":
            raise RuntimeError("simulated interruption")

    with pytest.raises(MigrationError):
        migrate_json_store(source, target, fault=interrupt)

    assert target.list_threads(True) == []
    assert target.list_nodes() == []
