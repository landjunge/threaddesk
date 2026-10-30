"""B01/B02: concurrent edits and committed notifications, isolated profiles."""
from argparse import Namespace

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.core.errors import ManagementError
from threaddesk.services.thread_management import manage, operation_status
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore


@pytest.fixture(params=[JsonStore, SQLiteStore])
def svc(request, tmp_path):
    return ThreadService(request.param(tmp_path))


def test_rolled_back_create_and_multifield_update_publish_nothing(svc):
    seen = []
    svc.bus.on("*", lambda name, data: seen.append((name, data)))
    with pytest.raises(ManagementError, match="nicht gefunden"):
        manage(svc, {"operation_id": "failed-create", "action": "create",
                     "expected_revision": 0,
                     "data": {"title": "Rollback", "parent_thread_id": "missing"}})
    assert svc.list() == []
    assert svc.current() is None
    assert seen == []
    thread = svc.create("Keep original")
    seen.clear()
    with pytest.raises(ManagementError):
        manage(svc, {"operation_id": "failed-update", "action": "update",
                     "id": thread.id, "expected_revision": thread.revision,
                     "data": {"title": "Must roll back", "status": "invalid"}})
    assert svc.get(thread.id).title == "Keep original"
    assert seen == []


def test_success_events_observe_committed_data_and_replay_is_silent(svc, caplog):
    observed = []

    def committed(name, data):
        # Reopening the store must see both the object and the operation receipt.
        reopened = type(svc.store)(svc.store.root)
        observed.append((name, reopened.get_thread(data["id"]).title,
                         reopened.get_management_operation("once") is not None))

    def broken_listener(*_):
        raise RuntimeError("Synthetic subscriber failure")

    svc.bus.on("thread.created", broken_listener)
    svc.bus.on("*", committed)
    args = {"operation_id": "once", "action": "create",
            "expected_revision": 0, "data": {"title": "Committed first"}}
    result = manage(svc, args)
    assert observed == [("thread.created", "Committed first", True),
                        ("thread.switched", "Committed first", True)]
    assert "Event listener failed after commit" in caplog.text
    assert operation_status(svc, {"operation_id": "once"})["result"] == result
    assert manage(svc, args)["duplicate"]
    assert len(observed) == 2
    assert len(svc.list()) == 1


def test_nested_notification_scope_discards_failed_inner_work(svc):
    seen = []
    svc.bus.on("*", lambda name, _: seen.append(name))
    with svc.bus.defer_until_commit():
        svc.bus.emit("outer")
        with pytest.raises(ValueError):
            with svc.bus.defer_until_commit():
                svc.bus.emit("rolled-back-inner")
                raise ValueError("Synthetic rollback")
        with svc.bus.defer_until_commit():
            svc.bus.emit("committed-inner")
        assert seen == []
    assert seen == ["outer", "committed-inner"]


def test_snapshot_and_restore_are_revision_bound_and_replayable(svc):
    thread = svc.create("Snapshots")
    snapshot_args = {"operation_id": "snapshot", "action": "snapshot",
                     "id": thread.id, "expected_revision": thread.revision,
                     "data": {"label": "Before changes"}}
    saved = manage(svc, snapshot_args)
    assert len(svc.snapshots(thread.id)) == 1
    assert manage(svc, snapshot_args)["duplicate"]
    svc.set_note("Newer contents", thread.id)
    restore_args = {"operation_id": "restore", "action": "restore_snapshot",
                    "id": thread.id, "expected_revision": saved["revision"],
                    "data": {"snapshot_id": saved["snapshot"]["id"]}}
    with pytest.raises(ManagementError) as stale:
        manage(svc, restore_args)
    assert stale.value.code == "revision_conflict"
    assert svc.get(thread.id).context.notes == "Newer contents"
    restore_args["expected_revision"] = svc.get(thread.id).revision
    restored = manage(svc, restore_args)
    assert restored["thread"]["context"]["notes"] == ""
    assert manage(svc, restore_args)["duplicate"]
    assert len(svc.snapshots(thread.id)) == 1


def test_cli_explicit_revision_conflict_and_exact_replay(svc):
    from threaddesk.ui.thread_cli_mutations import change
    thread = svc.create("CLI")
    args = Namespace(operation_id="cli-note", expected_revision=thread.revision)
    first = change(svc, args, "set_note", {"text": "First"}, key=thread.id)
    assert change(svc, args, "set_note", {"text": "First"}, key=thread.id)["duplicate"]
    with pytest.raises(ManagementError) as collision:
        change(svc, args, "set_note", {"text": "Different"}, key=thread.id)
    assert collision.value.code == "operation_conflict"
    args.operation_id = "cli-stale"
    with pytest.raises(ManagementError) as stale:
        change(svc, args, "set_note", {"text": "Stale"}, key=thread.id)
    assert stale.value.code == "revision_conflict"
    assert svc.get(thread.id).revision == first["revision"]
    assert svc.get(thread.id).context.notes == "First"


def test_cli_delete_flags_do_not_bypass_preview_bound_purge(svc, monkeypatch):
    from threaddesk.ui import cli
    thread = svc.create("Explicit legacy deletion fixture")
    thread = svc.archive(thread.id)
    monkeypatch.setattr(cli, "_svc", lambda: svc)
    for flags in (["--yes"], ["--yes", "--legacy-permanent"]):
        assert cli.main(["delete", thread.id, *flags]) == 2
    assert svc.get(thread.id).title == thread.title


def test_cli_command_flags_reject_stale_edit_without_fresh_retry(svc, monkeypatch):
    from threaddesk.ui import cli
    thread = svc.create("CLI parser contract")
    monkeypatch.setattr(cli, "_svc", lambda: svc)
    command = ["note", "First", "--id", thread.id,
               "--operation-id", "explicit-note", "--expected-revision", str(thread.revision)]
    assert cli.main(command) == 0
    assert cli.main(command) == 0
    assert cli.main([*command[:2], *command[2:4], "--operation-id", "stale-note",
                     "--expected-revision", str(thread.revision)]) == 2
    assert svc.get(thread.id).context.notes == "First"


@pytest.mark.parametrize("backend", ["json", "sqlite"])
def test_http_rejects_missing_and_stale_preconditions_and_preserves_saved_text(tmp_path, monkeypatch, backend):
    from http_ui_client import UIClient
    from threaddesk.ui.server import create_app
    monkeypatch.setenv("THREADDESK_HOME", str(tmp_path))
    monkeypatch.setenv("THREADDESK_STORAGE", backend)
    svc = ThreadService((SQLiteStore if backend == "sqlite" else JsonStore)(tmp_path))
    thread = svc.create("Two editors")
    client = UIClient(create_app())
    missing = client.post(f"/threads/{thread.id}/note", data={"text": "No preconditions"})
    assert missing.status_code == 428
    assert svc.get(thread.id).context.notes == ""
    args = {"text": "First writer", "expected_revision": thread.revision, "operation_id": "http-first"}
    first = client.post(f"/threads/{thread.id}/note", data=args)
    assert first.status_code == 200
    duplicate = client.post(f"/threads/{thread.id}/note", data=args)
    assert duplicate.status_code == 200 and duplicate.headers["X-ThreadDesk-Duplicate"] == "true"
    second = client.post(f"/threads/{thread.id}/note", data={**args, "operation_id": "http-second", "text": "Unsaved draft"})
    assert second.status_code == 409
    assert second.headers["X-ThreadDesk-Error-Code"] == "revision_conflict"
    assert svc.get(thread.id).context.notes == "First writer"
    conflict = client.post(f"/threads/{thread.id}/note", data={**args, "text": "Changed payload"})
    assert conflict.status_code == 409
    assert conflict.headers["X-ThreadDesk-Error-Code"] == "operation_conflict"
