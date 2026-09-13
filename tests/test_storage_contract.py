"""Contract tests reusable for JsonStore and the future SQLiteStore."""

from __future__ import annotations

from pathlib import Path

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.core.models import GraphEvent, KnowledgeNode, Relation, Snapshot, ThreadContext, new_thread
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore


@pytest.fixture(params=[JsonStore, SQLiteStore], ids=["json", "sqlite"])
def store(request: pytest.FixtureRequest, tmp_path: Path):
    return request.param(tmp_path)


def test_thread_snapshot_and_current_contract(store) -> None:
    thread = new_thread("Vertrag")
    store.save_thread(thread)
    store.set_current_id(thread.id)
    snapshot = Snapshot("snap-1", thread.id, "2026-01-01T00:00:00+00:00", "Stand", ThreadContext())
    store.save_snapshot(snapshot)

    assert store.get_thread(thread.id).to_dict() == thread.to_dict()
    assert store.get_current_id() == thread.id
    assert store.list_snapshots(thread.id)[0].to_dict() == snapshot.to_dict()


def test_graph_and_event_contract(store) -> None:
    node = KnowledgeNode("node-1", "project", "ThreadDesk")
    other = KnowledgeNode("node-2", "task", "Umbau")
    relation = Relation("relation-1", node.id, other.id, "contains")
    event = GraphEvent("event-1", "relation.created", relation.id, "relation", 1, "2026-01-01T00:00:00+00:00")
    store.save_node(node)
    store.save_node(other)
    store.save_relation(relation)
    store.append_graph_event(event)

    assert [item.id for item in store.list_nodes()] == ["node-2", "node-1"]
    assert store.list_relations()[0].to_dict() == relation.to_dict()
    assert store.list_graph_events()[0].to_dict() == event.to_dict()


def test_artifact_contract_and_path_guard(store) -> None:
    text_path = store.write_text_artifact("report.txt", "fertig\n")
    json_path = store.write_json_artifact("report.json", {"ok": True})

    assert text_path.read_text(encoding="utf-8") == "fertig\n"
    assert json_path.read_text(encoding="utf-8").endswith("\n")
    with pytest.raises(ValueError):
        store.artifact_path("../outside.json")


class StoreAdapter:
    """Structural store: deliberately not a JsonStore subclass."""

    def __init__(self, wrapped: JsonStore) -> None:
        self.wrapped = wrapped

    def __getattr__(self, name: str):
        return getattr(self.wrapped, name)


def test_thread_service_accepts_the_store_contract(tmp_path: Path) -> None:
    service = ThreadService(store=StoreAdapter(JsonStore(tmp_path)))
    created = service.create("Struktureller Vertrag")

    assert service.current().id == created.id
    assert service.list()[0].title == "Struktureller Vertrag"


def test_sqlite_schema_is_versioned_indexed_and_fts_ready(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path)
    version = store.connection.execute("SELECT version FROM schema_info").fetchone()[0]
    objects = {
        row[0]: row[1]
        for row in store.connection.execute(
            "SELECT name, type FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
        )
    }

    assert version == 3
    assert objects["idx_threads_status_updated"] == "index"
    assert objects["idx_snapshots_thread_created"] == "index"
    assert objects["idx_nodes_kind_status_updated"] == "index"
    assert objects["search_index"] == "table"
    assert objects["source_records"] == "table"
    assert objects["idx_source_records_target"] == "index"
    assert objects["artifacts"] == "table"
    assert objects["node_artifacts"] == "table"
    assert objects["idx_node_artifacts_sha"] == "index"


def test_application_code_uses_no_private_json_store_members() -> None:
    root = Path(__file__).parents[1] / "src" / "threaddesk"
    application = "\n".join(
        path.read_text(encoding="utf-8")
        for folder in ("api", "services", "ui")
        for path in (root / folder).rglob("*.py")
    )
    assert ".store.root" not in application
    assert ".store._write_json" not in application
