"""Deterministic, read-only planning for Notion bundle imports."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from threaddesk.core.import_models import DiffKind
from threaddesk.core.models import KnowledgeNode
from threaddesk.core.provenance import SourceRecord
from threaddesk.services.migration.diff import DryRunPlanner, node_target_hash
from threaddesk.services.migration.mapper import NotionMapper
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore


class FakeBundle:
    def __init__(self, objects, *, relations=(), exclusions=(), content=None) -> None:
        self.bundle_sha256 = "b" * 64
        self.manifest = {
            "export_id": "export-1",
            "source_workspace_id": "workspace-1",
        }
        self._objects = tuple(objects)
        self._relations = tuple(relations)
        self._exclusions = tuple(exclusions)
        self._content = dict(content or {})

    def iter_objects(self):
        yield from self._objects

    def iter_relations(self):
        yield from self._relations

    def iter_exclusions(self):
        yield from self._exclusions

    def read_text(self, path: str) -> str:
        return self._content[path]


def notion_object(
    source_id: str = "page-1",
    *,
    title: str = "ThreadDesk",
    suggested_kind: str = "project",
    status: str = "active",
    archived: bool = False,
    content_path: str | None = "content/page-1.md",
    properties: dict | None = None,
) -> dict:
    return {
        "source_id": source_id,
        "title": title,
        "source_path": f"NetzwerkPunkt/{title}",
        "source_url": f"https://www.notion.so/{source_id}",
        "source_type": "page",
        "parent_id": None,
        "last_edited_at": "2026-09-12T20:00:00+00:00",
        "properties": properties if properties is not None else {"status": status},
        "content_path": content_path,
        "content_sha256": "c" * 64 if content_path else None,
        "archived": archived,
        "suggested_kind": suggested_kind,
        "mapping_reason": "Explicit exporter proposal",
    }


def mapped_single(**updates):
    item = notion_object(**updates)
    content = {item["content_path"]: "# Original\n\nUnknown block: <mystery />\n"} if item["content_path"] else {}
    mapped = NotionMapper().map(FakeBundle([item], content=content))
    return mapped.objects[0]


def source_record(mapped, target: KnowledgeNode, *, source_hash: str | None = None) -> SourceRecord:
    return SourceRecord(
        source_system="notion",
        source_id=mapped.source_id,
        target_id=target.id,
        source_hash=source_hash or mapped.source_hash,
        target_hash=node_target_hash(target),
        bundle_id="older-export",
        imported_at="2026-09-11T20:00:00+00:00",
        mapping_rule=mapped.provenance.mapping_rule,
    )


def test_mapper_preserves_original_content_properties_and_provenance() -> None:
    properties = {
        "status": "active",
        "unknown_blocks": [{"type": "mystery", "raw": {"x": 1}}],
    }
    item = notion_object(properties=properties)
    mapped = NotionMapper().map(
        FakeBundle([item], content={"content/page-1.md": "Original text\n"})
    ).objects[0]

    assert mapped.draft.id.startswith("notion-")
    assert mapped.draft.kind == "project"
    assert mapped.draft.status == "active"
    assert mapped.draft.details == "Original text\n"
    assert mapped.draft.metadata["source_properties"] == properties
    assert mapped.provenance.source_system == "notion"
    assert mapped.provenance.source_id == "page-1"
    assert mapped.provenance.bundle_id == "export-1"
    assert mapped.provenance.source_hash == mapped.source_hash


def test_same_input_maps_deterministically_and_models_are_immutable() -> None:
    first = mapped_single()
    second = mapped_single()

    assert first == second
    with pytest.raises(FrozenInstanceError):
        first.source_hash = "changed"
    with pytest.raises(TypeError):
        first.draft.metadata["new"] = True


def test_unknown_kind_is_preserved_as_open_document_not_confirmed_fact() -> None:
    mapped = mapped_single(suggested_kind="notion_database_widget")

    assert mapped.mapping_state == "open"
    assert mapped.draft.kind == "document"
    assert mapped.draft.status == "unverified"
    assert mapped.draft.metadata["suggested_kind"] == "notion_database_widget"


def test_relation_mapping_preserves_unknown_relation_as_open() -> None:
    first = notion_object("a", content_path=None)
    second = notion_object("b", content_path=None)
    bundle = FakeBundle(
        [first, second],
        relations=[
            {"source_id": "a", "target_id": "b", "kind": "contains"},
            {"source_id": "b", "target_id": "a", "kind": "notion_rollup"},
        ],
    )

    mapped = NotionMapper().map(bundle)

    assert mapped.relations[0].draft.kind == "contains"
    assert mapped.relations[0].mapping_state == "mapped"
    assert mapped.relations[1].draft.kind == "related_to"
    assert mapped.relations[1].mapping_state == "open"
    assert mapped.relations[1].source_kind == "notion_rollup"


def test_dry_run_classifies_new_and_does_not_need_a_writable_store() -> None:
    mapped = mapped_single()
    result = DryRunPlanner().plan_mapped(
        objects=(mapped,), relations=(), exclusions=(), existing_nodes=(), source_records=()
    )

    assert result.proposals[0].diff is DiffKind.NEW
    assert result.counts["new"] == 1


def test_validated_bundle_shape_maps_and_plans_as_one_read_only_flow() -> None:
    item = notion_object()
    bundle = FakeBundle(
        [item],
        exclusions=[{"source_id": "private-1", "title": "Private", "reason": "private"}],
        content={"content/page-1.md": "Original\n"},
    )

    result = DryRunPlanner().plan(
        bundle, existing_nodes=(), source_records=()
    )

    assert result.bundle_sha256 == "b" * 64
    assert result.proposals[0].diff is DiffKind.NEW
    assert result.exclusions[0].source_id == "private-1"
    assert set(result.counts) == {kind.value for kind in DiffKind}


def test_same_source_hash_is_noop_even_when_local_target_changed() -> None:
    mapped = mapped_single()
    target = mapped.draft.to_node()
    record = source_record(mapped, target)
    locally_changed = KnowledgeNode.from_dict({**target.to_dict(), "title": "Local title", "revision": 2})

    result = DryRunPlanner().plan_mapped(
        objects=(mapped,), relations=(), exclusions=(),
        existing_nodes=(locally_changed,), source_records=(record,),
    )

    assert result.proposals[0].diff is DiffKind.NOOP


def test_same_source_hash_with_missing_target_is_a_conflict() -> None:
    mapped = mapped_single()
    target = mapped.draft.to_node()
    record = source_record(mapped, target)

    result = DryRunPlanner().plan_mapped(
        objects=(mapped,), relations=(), exclusions=(),
        existing_nodes=(), source_records=(record,),
    )

    assert result.proposals[0].diff is DiffKind.CONFLICT
    assert result.proposals[0].reason == "target_missing"


def test_changed_source_is_update_when_target_remained_unchanged() -> None:
    mapped = mapped_single(title="New source title")
    old_target = KnowledgeNode.from_dict({**mapped.draft.to_node().to_dict(), "title": "Old title"})
    record = source_record(mapped, old_target, source_hash="a" * 64)

    result = DryRunPlanner().plan_mapped(
        objects=(mapped,), relations=(), exclusions=(),
        existing_nodes=(old_target,), source_records=(record,),
    )

    assert result.proposals[0].diff is DiffKind.UPDATE
    assert result.proposals[0].target_id == old_target.id


def test_changed_source_conflicts_with_locally_changed_or_missing_target() -> None:
    mapped = mapped_single(title="New source title")
    imported_target = KnowledgeNode.from_dict({**mapped.draft.to_node().to_dict(), "title": "Old title"})
    record = source_record(mapped, imported_target, source_hash="a" * 64)
    locally_changed = KnowledgeNode.from_dict(
        {**imported_target.to_dict(), "details": "Local work", "revision": 2}
    )

    changed = DryRunPlanner().plan_mapped(
        objects=(mapped,), relations=(), exclusions=(),
        existing_nodes=(locally_changed,), source_records=(record,),
    )
    missing = DryRunPlanner().plan_mapped(
        objects=(mapped,), relations=(), exclusions=(),
        existing_nodes=(), source_records=(record,),
    )

    assert changed.proposals[0].diff is DiffKind.CONFLICT
    assert missing.proposals[0].diff is DiffKind.CONFLICT


def test_similar_title_is_only_a_possible_duplicate() -> None:
    mapped = mapped_single(title="ThreadDesk Masterplan")
    existing = KnowledgeNode("local-1", "project", "ThreadDesk-Masterplan")

    result = DryRunPlanner().plan_mapped(
        objects=(mapped,), relations=(), exclusions=(),
        existing_nodes=(existing,), source_records=(),
    )

    assert result.proposals[0].diff is DiffKind.POSSIBLE_DUPLICATE
    assert result.proposals[0].target_id == "local-1"


def test_archived_source_is_archive_proposal_unless_local_target_changed() -> None:
    mapped = mapped_single(archived=True)
    target = KnowledgeNode.from_dict({**mapped.draft.to_node().to_dict(), "status": "active"})
    record = source_record(mapped, target, source_hash="a" * 64)

    result = DryRunPlanner().plan_mapped(
        objects=(mapped,), relations=(), exclusions=(),
        existing_nodes=(target,), source_records=(record,),
    )

    assert result.proposals[0].diff is DiffKind.ARCHIVE

    locally_changed = KnowledgeNode.from_dict(
        {**target.to_dict(), "details": "Local work", "revision": 2}
    )
    conflict = DryRunPlanner().plan_mapped(
        objects=(mapped,), relations=(), exclusions=(),
        existing_nodes=(locally_changed,), source_records=(record,),
    )
    assert conflict.proposals[0].diff is DiffKind.CONFLICT


def test_open_mapping_and_exclusions_remain_visible_in_dry_run() -> None:
    unknown = mapped_single(suggested_kind="unknown")
    exclusion = {"source_id": "private-1", "title": "Private", "reason": "private"}

    result = DryRunPlanner().plan_mapped(
        objects=(unknown,), relations=(), exclusions=(exclusion,),
        existing_nodes=(), source_records=(),
    )

    assert result.proposals[0].diff is DiffKind.OPEN
    assert result.exclusions[0].source_id == "private-1"
    assert result.counts["open"] == 1
    assert result.counts["excluded"] == 1


def test_missing_source_creates_no_automatic_delete_or_archive() -> None:
    absent = SourceRecord(
        "notion", "absent", "local-1", "a" * 64, "b" * 64,
        "old", "2026-09-11T20:00:00+00:00", "notion.v1",
    )

    result = DryRunPlanner().plan_mapped(
        objects=(), relations=(), exclusions=(),
        existing_nodes=(KnowledgeNode("local-1", "project", "Keep me"),),
        source_records=(absent,),
    )

    assert result.proposals == ()
    assert result.counts.get("delete", 0) == 0
    assert result.counts["archive"] == 0


@pytest.mark.parametrize("store_type", [JsonStore, SQLiteStore], ids=["json", "sqlite"])
def test_source_record_round_trips_through_storage_contract(tmp_path: Path, store_type) -> None:
    store = store_type(tmp_path)
    record = SourceRecord(
        "notion", "page-1", "node-1", "a" * 64, "b" * 64,
        "export-1", "2026-09-12T20:00:00+00:00", "notion.v1.suggested_kind",
    )

    store.save_source_record(record)

    assert store.get_source_record("notion", "page-1") == record
    assert store.list_source_records("notion") == [record]


def test_sqlite_v1_workspace_is_migrated_to_source_records_schema(tmp_path: Path) -> None:
    import sqlite3
    from threaddesk.storage.schema import V1_SCHEMA_SQL

    database = tmp_path / "threaddesk.sqlite3"
    tmp_path.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database)
    connection.executescript(V1_SCHEMA_SQL)
    connection.execute("INSERT INTO schema_info(version) VALUES (1)")
    connection.commit()
    connection.close()

    store = SQLiteStore(tmp_path)

    assert store.connection.execute("SELECT version FROM schema_info").fetchone()[0] == 2
    assert store.connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='source_records'"
    ).fetchone()[0] == "source_records"


def test_future_sqlite_schema_is_rejected_without_backporting_tables(tmp_path: Path) -> None:
    import sqlite3

    database = tmp_path / "threaddesk.sqlite3"
    connection = sqlite3.connect(database)
    connection.executescript(
        "CREATE TABLE schema_info(version INTEGER NOT NULL);"
        "INSERT INTO schema_info(version) VALUES (99);"
    )
    connection.close()

    with pytest.raises(RuntimeError, match="Nicht unterstützte Schema-Version"):
        SQLiteStore(tmp_path)

    check = sqlite3.connect(database)
    assert check.execute(
        "SELECT name FROM sqlite_master WHERE name='source_records'"
    ).fetchone() is None
    check.close()
