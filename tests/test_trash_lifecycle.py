"""Real lifecycle persistence, rollback, replay and backup, on both stores."""
from pathlib import Path

import pytest

from threaddesk.core.errors import ManagementError, NotFound
from threaddesk.core.models import KnowledgeNode, Relation, Snapshot, ThreadContext, WhiteboardEntry, new_thread
from threaddesk.services.trash import TrashService
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore
from threaddesk.storage.portable_backup import download_backup, restore_backup
from threaddesk.storage.json_migration import migrate_json_store


@pytest.fixture(params=[JsonStore, SQLiteStore], ids=["json", "sqlite"])
def store(request, tmp_path):
    return request.param(tmp_path / "source")


def seed(store):
    thread = new_thread("Original")
    thread.context.notes = "Geschichte erhalten"
    store.save_thread(thread)
    store.set_current_id(thread.id)
    store.save_snapshot(Snapshot("snapshot1", thread.id, "2026-10-26T00:00:00Z", "Alt", ThreadContext(notes="Snapshot")))
    store.append_whiteboard_entry(WhiteboardEntry("entry1", thread.id, "Test", "human",
        "2026-10-26T00:00:00Z", "note", "Whiteboard bleibt"))
    store.save_node(KnowledgeNode("node1", "project", "Projekt", metadata={"thread_id": thread.id}))
    store.save_node(KnowledgeNode("node2", "task", "Aufgabe"))
    store.save_relation(Relation("relation1", "node1", "node2", "contains"))
    return thread


def test_thread_roundtrip_preserves_payload_history_relations_and_selection(store):
    thread = seed(store)
    service = TrashService(store)
    before = store.get_thread(thread.id).to_dict()
    result = service.move(kind="thread", object_id=thread.id, expected_revision=thread.revision, operation_id="move")
    entry = result["entry"]
    assert entry["state"] == "trashed" and entry["generation"] == entry["revision"] == 1
    assert not store.list_threads(include_archived=True)
    assert [n.id for n in store.list_nodes()] == ["node2"]
    assert not store.list_relations()
    assert store.get_current_id() is None
    with pytest.raises(ManagementError, match="Papierkorb") as error:
        store.get_thread(thread.id)
    assert error.value.code == "object_in_trash"
    with pytest.raises(ManagementError):
        store.save_thread(thread)
    assert store.get_thread(thread.id, include_trashed=True).to_dict() == before
    assert service.preview(kind="thread", object_id=thread.id)["references"]["whiteboard"] == ["entry1"]
    restored = service.restore(trash_id=entry["trash_id"], generation=1, expected_revision=1, operation_id="restore")
    assert restored["entry"]["state"] == "restored"
    assert store.get_thread(thread.id).to_dict() == before
    assert store.list_whiteboard(thread.id)[0].content == "Whiteboard bleibt"
    assert store.list_snapshots(thread.id)[0].context.notes == "Snapshot"
    assert len(store.list_nodes()) == 2 and store.list_relations()[0].id == "relation1"
    assert store.get_current_id() is None


def test_replay_conflict_stale_revision_and_old_generation(store):
    thread = seed(store)
    service = TrashService(store)
    args = dict(kind="thread", object_id=thread.id, expected_revision=thread.revision, operation_id="move")
    first = service.move(**args)
    assert service.move(**args) == {**first, "duplicate": True}
    with pytest.raises(ManagementError) as error:
        service.move(**{**args, "actor": "different"})
    assert error.value.code == "operation_conflict"
    restore = dict(trash_id=first["entry"]["trash_id"], generation=1, expected_revision=1, operation_id="restore")
    service.restore(**restore)
    with pytest.raises(ManagementError) as error:
        service.move(**{**args, "operation_id": "stale", "expected_revision": thread.revision + 1})
    assert error.value.code == "revision_conflict"
    second = service.move(**{**args, "operation_id": "move2"})
    assert second["entry"]["generation"] == 2
    with pytest.raises(ManagementError) as error:
        service.restore(**{**restore, "operation_id": "old-restore"})
    assert error.value.code == "generation_conflict"
    assert service.restore(**restore)["duplicate"]
    assert store.object_in_trash("thread", thread.id)
    restarted = type(store)(store.root)
    assert TrashService(restarted).operation_status("move2")["result"]["entry"] == second["entry"]


def test_owner_receipt_reconciliation_is_exact_and_read_only_after_later_changes(store, monkeypatch):
    thread = seed(store)
    service = TrashService(store)
    args = dict(kind="thread", object_id=thread.id, expected_revision=thread.revision, operation_id="move")
    original = service.move(**args)
    entry = original['entry']
    service.restore(trash_id=entry['trash_id'], generation=1, expected_revision=1, operation_id='restore')
    monkeypatch.setattr(service, '_move_in_transaction', lambda **a: pytest.fail('Readback must not execute a mutation'))
    assert service.verify_recorded_request({'action':'move', **args}) == {'found':True, 'result':original}
    with pytest.raises(ManagementError) as mismatch:
        service.verify_recorded_request({'action':'move', **args, 'actor':'different'})
    assert mismatch.value.code == 'operation_conflict'
    assert service.verify_recorded_request({'action':'move', **args, 'operation_id':'absent'}) == {'found':False, 'result':None}


@pytest.mark.parametrize("kind,object_id", [("node", "node1"), ("relation", "relation1")])
def test_node_relation_roundtrip_and_reference_blockers(store, kind, object_id):
    seed(store)
    service = TrashService(store)
    moved = service.move(kind=kind, object_id=object_id, expected_revision=1, operation_id="move")
    assert not store.list_relations()
    preview = service.purge_preview(moved["entry"]["trash_id"])
    if kind == "node":
        assert preview["blockers"] == ["referenced_object"]
        with pytest.raises(ManagementError) as error:
            service.purge(trash_id=moved["entry"]["trash_id"], generation=1, expected_revision=1,
                          reference_digest=preview["reference_digest"], confirmation=preview["confirmation"], operation_id="purge")
        assert error.value.code == "purge_blocked"
    service.restore(trash_id=moved["entry"]["trash_id"], generation=1, expected_revision=1, operation_id="restore")
    assert store.list_relations()[0].id == "relation1"


def test_purge_needs_exact_preview_and_explicit_confirmation_keeps_original(store, tmp_path):
    original = tmp_path / "Original.txt"
    original.write_text("Erhalten")
    thread = new_thread("Ohne Referenzen")
    thread.context.files = [str(original)]
    store.save_thread(thread)
    service = TrashService(store)
    entry = service.move(kind="thread", object_id=thread.id, expected_revision=thread.revision, operation_id="move")["entry"]
    preview = service.purge_preview(entry["trash_id"])
    args = dict(trash_id=entry["trash_id"], generation=1, expected_revision=1,
                reference_digest=preview["reference_digest"], confirmation="yes", operation_id="purge")
    with pytest.raises(ManagementError) as error:
        service.purge(**args)
    assert error.value.code == "explicit_confirmation_required"
    result = service.purge(**{**args, "confirmation": preview["confirmation"]})
    assert result["entry"]["state"] == "purged"
    assert original.read_text() == "Erhalten"
    assert not store.list_threads(include_archived=True, include_trashed=True)
    assert service.purge(**{**args, "confirmation": preview["confirmation"]})["duplicate"]


def test_failed_operation_rolls_back_lifecycle_and_active_selection(store, monkeypatch):
    thread = seed(store)
    before = store.get_current_id()
    save = store.save_management_operation

    def fail(operation_id, data):
        if data.get("kind") == "lifecycle":
            raise RuntimeError("receipt failure")
        return save(operation_id, data)

    monkeypatch.setattr(store, "save_management_operation", fail)
    with pytest.raises(RuntimeError, match="receipt failure"):
        TrashService(store).move(kind="thread", object_id=thread.id, expected_revision=thread.revision, operation_id="move")
    assert not store.list_trash_entries()
    assert store.get_current_id() == before
    assert store.get_thread(thread.id).title == "Original"


def test_portable_backup_preserves_hidden_payload_and_restore_generation(store, tmp_path):
    thread = seed(store)
    entry = TrashService(store).move(kind="thread", object_id=thread.id,
        expected_revision=thread.revision, operation_id="move")["entry"]
    profile = restore_backup(download_backup(store), tmp_path / "restore")
    restored = type(store)(profile)
    service = TrashService(restored)
    assert not restored.list_threads(include_archived=True)
    assert service.get(entry["trash_id"]) == entry
    service.restore(trash_id=entry["trash_id"], generation=1, expected_revision=1, operation_id="restore")
    assert restored.get_thread(thread.id).context.notes == "Geschichte erhalten"
    assert restored.list_whiteboard(thread.id)[0].id == "entry1"


def test_migration_keeps_hidden_objects_and_receipt_keys(tmp_path):
    source = JsonStore(tmp_path / "json")
    thread = seed(source)
    entry = TrashService(source).move(kind="thread", object_id=thread.id,
        expected_revision=thread.revision, operation_id="move")["entry"]
    target = SQLiteStore(tmp_path / "sqlite")
    assert migrate_json_store(source, target)["status"] == "imported"
    assert migrate_json_store(source, target)["status"] == "noop"
    assert not target.list_threads(include_archived=True)
    service = TrashService(target)
    assert service.operation_status("move")["found"]
    assert service.get(entry["trash_id"]) == entry
    service.restore(trash_id=entry["trash_id"], generation=1, expected_revision=1, operation_id="restore")
    assert target.list_whiteboard(thread.id)[0].id == "entry1"


def test_owner_documents_migrate_atomically_and_existing_files_take_precedence(tmp_path):
    source = JsonStore(tmp_path / "json")
    thread = seed(source)
    documents = {"file-activity.json": {"schema_version": 1, "generation": 3, "events": []},
                 "graph-views.json": {"schema_version": 1, "generation": 4, "views": {}}}
    for name, value in documents.items():
        source.write_json_artifact(name, value)
    target = SQLiteStore(tmp_path / "sqlite")

    def fail(stage):
        if stage == "before_commit":
            raise RuntimeError("rollback")

    from threaddesk.storage.json_migration import MigrationError
    with pytest.raises(MigrationError):
        migrate_json_store(source, target, fault=fail)
    assert target.get_migrated_owner_document("file-activity.json") is None
    migrate_json_store(source, target)
    assert migrate_json_store(source, target)["status"] == "noop"
    assert not target.artifact_path("file-activity.json").exists()
    restarted = SQLiteStore(target.root)
    for name, value in documents.items():
        assert restarted.get_migrated_owner_document(name) == value
    from threaddesk.storage.owner_documents import read_owner_documents
    assert read_owner_documents(restarted) == documents
    updated = {"schema_version": 1, "generation": 5, "events": ["newer"]}
    restarted.write_json_artifact("file-activity.json", updated)
    assert read_owner_documents(restarted)["file-activity.json"] == updated


def test_library_index_follows_lifecycle_and_linked_originals_block_purge(store, tmp_path):
    from threaddesk.services.library_api import LibraryApplication
    from threaddesk.services.library_index import LibraryIndex
    thread = new_thread("Suchbarer Papierkorbtest")
    store.save_thread(thread)
    source = tmp_path / "source-files"
    source.mkdir()
    original = source / "Original.txt"
    original.write_text("Inhalt behalten")
    app = LibraryApplication(store)
    imported = app.call({"action": "import", "operation_id": "import",
        "data": {"source": str(source.resolve()), "thread_id": thread.id}})
    record_id = imported["files"][0]["record_id"]
    service = TrashService(store)
    entry = service.move(kind="thread", object_id=thread.id,
        expected_revision=store.get_thread(thread.id).revision, operation_id="move")["entry"]
    index = LibraryIndex(store.root / "library-files")
    assert index.status()["status"] == "ready"
    assert index.search("Papierkorbtest", entity_type="thread") == []
    assert not store.list_nodes()
    preview = service.purge_preview(entry["trash_id"])
    assert preview["references"]["library_records_preserved"] == [record_id]
    assert preview["blockers"] == ["referenced_object"]
    service.restore(trash_id=entry["trash_id"], generation=1, expected_revision=1, operation_id="restore")
    assert index.status()["status"] == "ready"
    assert index.search("Papierkorbtest", entity_type="thread")[0]["thread_id"] == thread.id
    assert store.list_nodes()[0].id == record_id
    assert original.read_text() == "Inhalt behalten"


def test_json_committed_crash_recovery_includes_receipt(tmp_path, monkeypatch):
    store = JsonStore(tmp_path)
    thread = seed(store)
    original = store._recover

    def crash():
        if store._journal.exists():
            raise RuntimeError("crash after journal publication")
        return original()

    monkeypatch.setattr(store, "_recover", crash)
    with pytest.raises(RuntimeError, match="crash"):
        TrashService(store).move(kind="thread", object_id=thread.id,
            expected_revision=thread.revision, operation_id="move")
    restarted = JsonStore(tmp_path)
    assert restarted.object_in_trash("thread", thread.id)
    assert restarted.get_current_id() is None
    assert TrashService(restarted).operation_status("move")["found"]


def test_legacy_revision_zero_can_be_trashed_and_rogue_writer_is_detected(tmp_path):
    import json
    store = JsonStore(tmp_path)
    thread = new_thread("Altdaten")
    path = store.threads_dir / (thread.id + ".json")
    path.write_text(json.dumps(thread.to_dict()))
    service = TrashService(store)
    entry = service.move(kind="thread", object_id=thread.id, expected_revision=0, operation_id="move")["entry"]
    rogue = json.loads(path.read_text())
    rogue["context"]["notes"] = "Unexpected old writer"
    path.write_text(json.dumps(rogue))
    with pytest.raises(ManagementError) as error:
        service.restore(trash_id=entry["trash_id"], generation=1, expected_revision=1, operation_id="restore")
    assert error.value.code == "object_changed_in_trash"
    assert store.object_in_trash("thread", thread.id)


def test_local_search_ignores_trash_and_restore_is_findable(store):
    from threaddesk.services.search import LocalFileOwnerPolicy, SearchService
    search = SearchService(store, LocalFileOwnerPolicy(store.workspace_path))
    thread = new_thread("LifecycleSearchUnique")
    store.save_thread(thread)
    search.set_enabled(True)
    for _ in range(30):
        if search.rebuild_batch()["status"] not in {"cleaning", "building"}:
            break
    assert search.search("LifecycleSearchUnique").hits[0].thread_id == thread.id
    service = TrashService(store)
    entry = service.move(kind="thread", object_id=thread.id, expected_revision=thread.revision, operation_id="move")["entry"]
    assert not search.search("LifecycleSearchUnique").hits
    service.restore(trash_id=entry["trash_id"], generation=1, expected_revision=1, operation_id="restore")
    assert search.search("LifecycleSearchUnique").hits[0].thread_id == thread.id


def test_snapshot_write_and_trash_share_one_writer_boundary(store, monkeypatch):
    from threading import Event, Thread
    thread = new_thread("Concurrent lifecycle")
    store.save_thread(thread)
    entered, release, moved = Event(), Event(), Event()
    failures, results = [], []

    def write_snapshot():
        writer = type(store)(store.root)
        require = writer.require_live_object

        def hold(kind, object_id):
            require(kind, object_id)
            entered.set()
            if not release.wait(10):
                raise RuntimeError("writer was not released")

        monkeypatch.setattr(writer, "require_live_object", hold)
        try:
            writer.save_snapshot(Snapshot("concurrent", thread.id, "2026-10-26T00:00:00Z", "Before trash", ThreadContext()))
        except BaseException as exc:
            failures.append(exc)
        finally:
            if hasattr(writer, "connection"):
                writer.connection.close()

    def move_thread():
        other = None
        try:
            other = type(store)(store.root)
            results.append(TrashService(other).move(kind="thread", object_id=thread.id,
                expected_revision=thread.revision, operation_id="concurrent-move"))
            moved.set()
        except BaseException as exc:
            failures.append(exc)
        finally:
            if other is not None and hasattr(other, "connection"):
                other.connection.close()

    writer = Thread(target=write_snapshot)
    mover = Thread(target=move_thread)
    writer.start()
    assert entered.wait(5)
    mover.start()
    try:
        assert not moved.wait(.2), "lifecycle moved between visibility check and write"
    finally:
        release.set()
        writer.join(10)
        mover.join(10)
    assert not failures and not writer.is_alive() and not mover.is_alive()
    assert moved.is_set()
    assert results[0]["entry"]["references"]["snapshots"] == ["concurrent"]
