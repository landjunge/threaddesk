"""Lost outer receipts can adopt only an exact, already committed owner result."""
from types import SimpleNamespace

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.core.errors import ManagementError
from threaddesk.services.commands.reconciliation import verify_owner_result
from threaddesk.services.graph_views import GraphViewService
from threaddesk.services.knowledge_memory import manage as knowledge_manage
from threaddesk.services.thread_management import manage as thread_manage
from threaddesk.services.trash import TrashService
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore
from test_library_api import library as library  # Shared explicit synthetic fixture.


@pytest.fixture(params=[JsonStore, SQLiteStore], ids=["json", "sqlite"])
def svc(request, tmp_path, monkeypatch):
    monkeypatch.delenv("THREADDESK_SOURCE_ROOTS", raising=False)
    return ThreadService(request.param(tmp_path))


def bytes_before_after(store):
    # SQLite may maintain reader slots in shared-memory control files. Domain
    # database and owner artifact bytes must remain unchanged by verification.
    return {str(path.relative_to(store.root)): path.read_bytes()
            for path in store.root.rglob("*") if path.is_file() and not path.name.endswith("-shm")}


def forbid_writes(monkeypatch, svc):
    def unexpected(*args, **kwargs):
        raise AssertionError("Verifier attempted a mutation or an external action")
    for name in ("save_management_operation", "save_thread", "save_node", "save_issued_handoff",
                 "write_json_artifact", "write_text_artifact"):
        monkeypatch.setattr(svc.store, name, unexpected)
    for name in ("create", "set_note", "issue_handoff", "connect", "transition_node"):
        monkeypatch.setattr(svc, name, unexpected)
    return unexpected


@pytest.mark.parametrize("command", ["thread_manage", "knowledge_manage"])
def test_management_owner_is_exact_public_and_inert_after_later_edit(svc, monkeypatch, command):
    thread = svc.create("Original context")
    if command == "thread_manage":
        args = {"action": "set_note", "operation_id": "domain-first", "id": thread.id,
                "expected_revision": thread.revision, "data": {"text": "Original stored note"}}
        original = thread_manage(svc, args)
    else:
        args = {"action": "save_reentry", "operation_id": "domain-first", "id": thread.id,
                "expected_revision": thread.revision,
                "data": {"summary": "Known handoff", "next_step": "Inspect only",
                         "source_ref": "synthetic", "source_revision": "1"}}
        original = knowledge_manage(svc, args)
    svc.set_note("A newer edit must remain untouched", thread.id)
    snapshot = bytes_before_after(svc.store)
    forbid_writes(monkeypatch, svc)
    verified = verify_owner_result(svc, command, args)
    assert verified["duplicate"]
    assert verified["revision"] == original["revision"]
    assert verified["thread"]["notes"].startswith('<untrusted source="threaddesk.notes">')
    assert svc.store.get_thread(thread.id).context.notes == "A newer edit must remain untouched"
    with pytest.raises(ManagementError) as wrong:
        verify_owner_result(svc, command, {**args, "expected_revision": args["expected_revision"] + 1})
    assert wrong.value.code == "operation_conflict"
    assert bytes_before_after(svc.store) == snapshot


def test_view_receipt_is_exact_after_owner_was_updated_and_never_saves(svc, monkeypatch):
    views = GraphViewService(svc.store)
    args = {"action": "save", "id": "known-view", "operation_id": "view-first", "expected_revision": 0,
            "data": {"title": "Before update", "state": {}}}
    first = views.manage(args)
    views.manage({**args, "operation_id": "view-second", "expected_revision": 1,
                  "data": {"title": "Current title", "state": {}}})
    snapshot = bytes_before_after(svc.store)
    forbidden = forbid_writes(monkeypatch, svc)
    monkeypatch.setattr(GraphViewService, "manage", forbidden)
    result = verify_owner_result(svc, "graph_view.manage", args)
    assert result == {**first, "duplicate": True}
    with pytest.raises(ManagementError) as wrong:
        verify_owner_result(svc, "graph_view.manage", {**args, "data": {"title": "Wrong", "state": {}}})
    assert wrong.value.code == "operation_conflict"
    assert bytes_before_after(svc.store) == snapshot


def test_trash_move_and_restore_results_are_historical_and_read_only(svc, monkeypatch):
    thread = svc.create("Lifecycle owner")
    trash = TrashService(svc.store)
    move = {"kind": "thread", "object_id": thread.id, "expected_revision": thread.revision, "operation_id": "move-first"}
    moved = trash.move(**move)
    entry = moved["entry"]
    restore = {"trash_id": entry["trash_id"], "generation": entry["generation"],
               "expected_revision": entry["revision"], "operation_id": "restore-first"}
    restored = trash.restore(**restore)
    snapshot = bytes_before_after(svc.store)
    forbidden = forbid_writes(monkeypatch, svc)
    monkeypatch.setattr(TrashService, "move", forbidden)
    monkeypatch.setattr(TrashService, "restore", forbidden)
    assert verify_owner_result(svc, "trash.move", move) == {**moved, "duplicate": True}
    assert verify_owner_result(svc, "trash.restore", restore) == {**restored, "duplicate": True}
    with pytest.raises(ManagementError) as conflict:
        verify_owner_result(svc, "trash.move", {**move, "actor": "Another actor"})
    assert conflict.value.code == "operation_conflict"
    assert bytes_before_after(svc.store) == snapshot


def test_issue_handoff_uses_immutable_receipt_without_current_source_lookup(svc, monkeypatch):
    from threaddesk.services.issued_handoffs import IssuedHandoffs
    thread = svc.create("Handoff owner")
    svc.gate_set(cooldown_seconds=0)
    args = {"operation_id": "issue-first", "id": thread.id, "expected_revision": thread.revision}
    issued = svc.issue_handoff(args)
    svc.set_note("Newer state", thread.id)
    snapshot = bytes_before_after(svc.store)
    forbidden = forbid_writes(monkeypatch, svc)
    monkeypatch.setattr(IssuedHandoffs, "__init__", forbidden)
    result = verify_owner_result(svc, "issue_handoff", args)
    assert result == {**issued, "duplicate": True}
    with pytest.raises(ManagementError) as wrong:
        verify_owner_result(svc, "issue_handoff", {**args, "target": "codex"})
    assert wrong.value.code == "operation_conflict"
    assert bytes_before_after(svc.store) == snapshot


@pytest.mark.parametrize("command", ["server_sync.run", "module.probe.record", "backup.restore", "missing.command"])
def test_unproven_effects_are_not_inferred_from_current_state(svc, command):
    snapshot = bytes_before_after(svc.store)
    with pytest.raises(ManagementError) as unknown:
        verify_owner_result(svc, command, {"operation_id": "no-proof", "expected_revision": 0})
    assert unknown.value.code == "owner_receipt_unverifiable"
    assert bytes_before_after(svc.store) == snapshot


def test_missing_owner_receipt_remains_unverifiable(svc):
    args = {"action": "create", "operation_id": "never-started", "expected_revision": 0,
            "data": {"title": "Not created"}}
    snapshot = bytes_before_after(svc.store)
    with pytest.raises(ManagementError) as missing:
        verify_owner_result(svc, "thread_manage", args)
    assert missing.value.code == "owner_receipt_unverifiable"
    assert svc.list() == []
    assert bytes_before_after(svc.store) == snapshot


@pytest.mark.parametrize("status", ["launch_requested", "unknown", "failed"])
def test_file_open_owner_lookup_never_reopens_or_promotes_unknown(library, monkeypatch, status):
    from threaddesk.services.library_files import LibraryFileService
    from threaddesk.services.library_files import state
    _app, svc, identity, _node, _original, _root = library
    launches = []
    files = LibraryFileService(svc.store, handler_resolver=lambda _: "/System/Applications/TextEdit.app",
                               opener=lambda *args, **kwargs: (launches.append(args), SimpleNamespace(returncode=0))[1])
    args = {"action": "open", "id": identity, "operation_id": "open-first", "expected_revision": 1}
    files.open(identity, operation_id="open-first", expected_revision=1)
    if status != "launch_requested":
        document = state.read_state(files.root)
        document["operations"]["open-first"]["result"]["status"] = status
        state.write_state(files.root, document)
    snapshot = bytes_before_after(svc.store)
    forbidden = forbid_writes(monkeypatch, svc)
    monkeypatch.setattr(LibraryFileService, "open", forbidden)
    monkeypatch.setattr(LibraryFileService, "manage", forbidden)
    if status == "launch_requested":
        assert verify_owner_result(svc, "library_manage", args)["status"] == "launch_requested"
    else:
        with pytest.raises(ManagementError) as unknown:
            verify_owner_result(svc, "library_manage", args)
        assert unknown.value.code == "owner_receipt_unverifiable"
    assert len(launches) == 1
    assert bytes_before_after(svc.store) == snapshot


def test_file_mutation_uses_exact_owner_request_hash_and_no_current_file_read(library, monkeypatch):
    from threaddesk.services.library_files import LibraryFileService
    _app, svc, identity, _node, _original, _root = library
    files = LibraryFileService(svc.store)
    args = {"action": "rename", "id": identity, "operation_id": "rename-first",
            "expected_revision": 1, "data": {"filename": "Confirmed.txt"}}
    first = files.manage(args)
    files.manage({"action": "rename", "id": identity, "operation_id": "rename-second",
                  "expected_revision": 2, "data": {"filename": "Newer.txt"}})
    snapshot = bytes_before_after(svc.store)
    forbidden = forbid_writes(monkeypatch, svc)
    monkeypatch.setattr(LibraryFileService, "info", forbidden)
    monkeypatch.setattr(LibraryFileService, "manage", forbidden)
    actual = verify_owner_result(svc, "library_manage", args)
    assert actual == {**first, "duplicate": True}
    with pytest.raises(ManagementError) as wrong:
        verify_owner_result(svc, "library_manage", {**args, "data": {"filename": "Wrong.txt"}})
    assert wrong.value.code == "operation_conflict"
    assert bytes_before_after(svc.store) == snapshot
