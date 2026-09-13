"""Atomic import, rollback and restart boundaries for TD-NM7."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import zipfile

import pytest

from threaddesk.core.models import KnowledgeNode
from threaddesk.services.migration import DryRunPlanner, validate_bundle
from threaddesk.services.migration.importer import (
    AtomicImportError,
    AtomicImportService,
    ImportBlocked,
    ImportOutcomeUncertain,
)
from threaddesk.storage.sqlite_store import SQLiteStore


def _json_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_import_bundle(
    path: Path,
    *,
    export_id: str = "export-1",
    project_title: str = "ThreadDesk",
    suggested_kind: str = "project",
    relation_kind: str = "contains",
    same_content: bool = False,
) -> Path:
    project_content = f"# {project_title}\n\nOriginal project text.\n".encode()
    task_content = (
        project_content if same_content else b"# Import\n\nBuild atomic import.\n"
    )
    objects = [
        {
            "source_id": "page-project",
            "title": project_title,
            "source_path": f"NetzwerkPunkt/{project_title}",
            "source_url": "https://www.notion.so/page-project",
            "source_type": "page",
            "parent_id": None,
            "last_edited_at": "2026-09-12T20:00:00+00:00",
            "properties": {"status": "active"},
            "content_path": "content/page-project.md",
            "content_sha256": _sha256(project_content),
            "archived": False,
            "suggested_kind": suggested_kind,
            "mapping_reason": "Explicit exporter proposal",
        },
        {
            "source_id": "page-task",
            "title": "Atomic import",
            "source_path": "NetzwerkPunkt/ThreadDesk/Atomic import",
            "source_url": "https://www.notion.so/page-task",
            "source_type": "page",
            "parent_id": "page-project",
            "last_edited_at": "2026-09-12T20:00:00+00:00",
            "properties": {"status": "ready"},
            "content_path": "content/page-task.md",
            "content_sha256": _sha256(task_content),
            "archived": False,
            "suggested_kind": "task",
            "mapping_reason": "Explicit exporter proposal",
        },
    ]
    relations = [
        {"source_id": "page-project", "target_id": "page-task", "kind": relation_kind}
    ]
    files = {
        "objects.ndjson": b"".join(_json_bytes(item) for item in objects),
        "relations.ndjson": b"".join(_json_bytes(item) for item in relations),
        "exclusions.json": _json_bytes([]),
        "report.md": b"# Export report\n\nTwo objects.\n",
        "content/page-project.md": project_content,
        "content/page-task.md": task_content,
    }
    manifest = {
        "format": "threaddesk-notion-bundle-v1",
        "schema_version": 1,
        "export_id": export_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_workspace_id": "workspace-1",
        "roots": ["page-project"],
        "counts": {
            "objects": 2,
            "relations": 1,
            "content": 2,
            "attachments": 0,
            "exclusions": 0,
        },
        "files": {
            name: {"sha256": _sha256(data), "size": len(data)}
            for name, data in files.items()
        },
    }
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", _json_bytes(manifest))
        for name, data in files.items():
            archive.writestr(name, data)
    return path


def plan_for(store: SQLiteStore, path: Path):
    bundle = validate_bundle(path)
    plan = DryRunPlanner().plan(
        bundle,
        existing_nodes=store.list_nodes(),
        source_records=store.list_source_records("notion"),
    )
    return bundle, plan


def logical(store: SQLiteStore) -> dict:
    return {
        "nodes": [item.to_dict() for item in store.list_nodes()],
        "relations": [item.to_dict() for item in store.list_relations()],
        "events": [item.to_dict() for item in store.list_graph_events()],
        "sources": [item.to_dict() for item in store.list_source_records()],
        "artifacts": store.list_artifacts(),
        "links": store.list_node_artifacts(),
    }


def test_confirmed_plan_imports_whole_batch_with_evidence(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "workspace")
    path = write_import_bundle(tmp_path / "notion.tdbundle")
    original_hash = _sha256(path.read_bytes())
    bundle, plan = plan_for(store, path)

    result = AtomicImportService(store).commit(bundle, plan)

    assert result["status"] == "committed"
    assert result["counts"] == {"created": 2, "updated": 0, "archived": 0, "relations": 1}
    assert len(store.list_nodes()) == 2
    assert len(store.list_relations()) == 1
    assert len(store.list_source_records("notion")) == 2
    assert len(store.list_artifacts()) == 2
    assert len(store.list_node_artifacts()) == 2
    assert sorted(event.name for event in store.list_graph_events()) == [
        "import.node.created", "import.node.created", "import.relation.created"
    ]
    archived_bundle = Path(result["bundle_path"])
    assert archived_bundle.is_file()
    assert _sha256(archived_bundle.read_bytes()) == original_hash
    assert Path(result["backup_path"]).is_dir()
    assert Path(result["report_path"]).is_file()


def test_identical_second_import_is_idempotent_and_creates_no_second_backup(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "workspace")
    path = write_import_bundle(tmp_path / "same.tdbundle")
    bundle, plan = plan_for(store, path)
    service = AtomicImportService(store)
    first = service.commit(bundle, plan)
    before = logical(store)
    backups = list((store.root / "backups").glob("*.complete"))

    second_bundle, second_plan = plan_for(store, path)
    second = service.commit(second_bundle, second_plan)

    assert second == first
    assert logical(store) == before
    assert list((store.root / "backups").glob("*.complete")) == backups


def test_logically_identical_new_export_writes_no_nodes_relations_or_events(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "workspace")
    first_path = write_import_bundle(tmp_path / "first.tdbundle", export_id="export-1")
    first_bundle, first_plan = plan_for(store, first_path)
    AtomicImportService(store).commit(first_bundle, first_plan)
    before = logical(store)

    second_path = write_import_bundle(tmp_path / "second.tdbundle", export_id="export-2")
    second_bundle, second_plan = plan_for(store, second_path)
    result = AtomicImportService(store).commit(second_bundle, second_plan)

    assert result["counts"] == {"created": 0, "updated": 0, "archived": 0, "relations": 0}
    assert logical(store) == before


def test_changed_source_updates_unchanged_target_and_replaces_content_link(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "workspace")
    first_path = write_import_bundle(tmp_path / "first.tdbundle", export_id="export-1")
    first_bundle, first_plan = plan_for(store, first_path)
    AtomicImportService(store).commit(first_bundle, first_plan)
    project_before = next(item for item in store.list_nodes() if item.kind == "project")

    changed_path = write_import_bundle(
        tmp_path / "changed.tdbundle",
        export_id="export-2",
        project_title="ThreadDesk updated",
    )
    changed_bundle, changed_plan = plan_for(store, changed_path)
    result = AtomicImportService(store).commit(changed_bundle, changed_plan)
    project_after = store.get_node(project_before.id)

    assert result["counts"] == {"created": 0, "updated": 1, "archived": 0, "relations": 0}
    assert project_after.title == "ThreadDesk updated"
    assert project_after.revision == project_before.revision + 1
    assert store.get_source_record("notion", "page-project").bundle_id == "export-2"
    project_links = [
        item for item in store.list_node_artifacts() if item["node_id"] == project_before.id
    ]
    assert len(project_links) == 1


def test_identical_content_is_published_once_and_linked_to_both_nodes(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "workspace")
    path = write_import_bundle(tmp_path / "shared.tdbundle", same_content=True)
    bundle, plan = plan_for(store, path)

    AtomicImportService(store).commit(bundle, plan)

    assert len(store.list_artifacts()) == 1
    assert len(store.list_node_artifacts()) == 2


def test_conflict_is_blocked_before_backup_or_batch_write(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "workspace")
    first_path = write_import_bundle(tmp_path / "first.tdbundle")
    bundle, plan = plan_for(store, first_path)
    AtomicImportService(store).commit(bundle, plan)
    project = next(item for item in store.list_nodes() if item.kind == "project")
    project.details = "Local work that must not be overwritten"
    project.revision += 1
    store.save_node(project)
    before = logical(store)
    batches_before = store.list_import_batches()
    backups_before = list((store.root / "backups").glob("*.complete"))

    changed_path = write_import_bundle(
        tmp_path / "changed.tdbundle", export_id="export-2", project_title="ThreadDesk changed"
    )
    changed_bundle, changed_plan = plan_for(store, changed_path)

    with pytest.raises(ImportBlocked, match="conflict"):
        AtomicImportService(store).commit(changed_bundle, changed_plan)

    assert logical(store) == before
    assert store.list_import_batches() == batches_before
    assert list((store.root / "backups").glob("*.complete")) == backups_before


@pytest.mark.parametrize(
    "stage",
    ["after_backup", "after_stage", "after_publish", "during_transaction", "before_commit"],
)
def test_failure_before_commit_rolls_back_all_product_data(tmp_path: Path, stage: str) -> None:
    store = SQLiteStore(tmp_path / "workspace")
    path = write_import_bundle(tmp_path / f"{stage}.tdbundle")
    bundle, plan = plan_for(store, path)

    def fail(current: str) -> None:
        if current == stage:
            raise RuntimeError("simulated interruption")

    with pytest.raises(AtomicImportError):
        AtomicImportService(store, fault=fail).commit(bundle, plan)

    assert store.list_nodes() == []
    assert store.list_relations() == []
    assert store.list_source_records() == []
    assert store.list_artifacts() == []
    assert store.list_node_artifacts() == []
    assert not list((store.root / "artifacts").glob("*"))
    assert store.list_import_batches()[-1]["status"] == "rolled_back"


def test_failure_before_backup_writes_nothing(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "workspace")
    path = write_import_bundle(tmp_path / "early.tdbundle")
    bundle, plan = plan_for(store, path)

    def fail(stage: str) -> None:
        if stage == "before_backup":
            raise RuntimeError("stop")

    with pytest.raises(AtomicImportError):
        AtomicImportService(store, fault=fail).commit(bundle, plan)

    assert store.list_import_batches() == []
    assert not (store.root / "backups").exists()


def test_failure_after_commit_is_reported_as_uncertain_and_retry_is_safe(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "workspace")
    path = write_import_bundle(tmp_path / "after.tdbundle")
    bundle, plan = plan_for(store, path)

    def fail(stage: str) -> None:
        if stage == "after_commit":
            raise RuntimeError("client lost response")

    with pytest.raises(ImportOutcomeUncertain) as caught:
        AtomicImportService(store, fault=fail).commit(bundle, plan)

    committed = store.get_import_batch(caught.value.batch_id)
    assert committed["status"] == "committed"
    assert len(store.list_nodes()) == 2
    again_bundle, again_plan = plan_for(store, path)
    again = AtomicImportService(store).commit(again_bundle, again_plan)
    assert again["id"] == committed["id"]
    assert len(store.list_nodes()) == 2


def test_restore_creates_verified_profile_with_exact_preimport_state(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "workspace")
    store.save_node(KnowledgeNode("existing", "project", "Before import"))
    before = logical(store)
    path = write_import_bundle(tmp_path / "restore.tdbundle")
    bundle, plan = plan_for(store, path)
    service = AtomicImportService(store)
    result = service.commit(bundle, plan)

    restored_path = service.restore(result["id"], tmp_path / "restored")
    restored = SQLiteStore(restored_path)

    assert logical(restored) == before


def test_insufficient_disk_space_stops_before_backup(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "workspace")
    path = write_import_bundle(tmp_path / "full.tdbundle")
    bundle, plan = plan_for(store, path)

    with pytest.raises(AtomicImportError, match="disk_space"):
        AtomicImportService(store, disk_free=lambda _path: 0).commit(bundle, plan)

    assert store.list_import_batches() == []
    assert not (store.root / "backups").exists()


@pytest.mark.parametrize(
    ("suggested_kind", "relation_kind"),
    [("unknown_kind", "contains"), ("project", "unknown_relation")],
)
def test_open_object_or_relation_mapping_is_not_committed(
    tmp_path: Path, suggested_kind: str, relation_kind: str
) -> None:
    store = SQLiteStore(tmp_path / "workspace")
    path = write_import_bundle(
        tmp_path / "open.tdbundle",
        suggested_kind=suggested_kind,
        relation_kind=relation_kind,
    )
    bundle, plan = plan_for(store, path)

    with pytest.raises(ImportBlocked, match="open"):
        AtomicImportService(store).commit(bundle, plan)

    assert store.list_nodes() == []
    assert store.list_import_batches() == []
