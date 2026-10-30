"""Thread-backed whiteboard lifecycle: durable receipts, projections and trash."""
from __future__ import annotations

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.core.errors import ManagementError
from threaddesk.services.commands import CommandApplication
from threaddesk.services.whiteboard_lifecycle import WhiteboardService, effective_entries
from threaddesk.services.graph_changes import GraphChangeService
from threaddesk.services.trash import TrashService
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore


@pytest.fixture(params=[JsonStore, SQLiteStore], ids=["json", "sqlite"])
def app(request, tmp_path):
    return CommandApplication(ThreadService(store=request.param(tmp_path)))


def invoke(app, command, arguments, *, operation=None, revision=None):
    request = {"version": 1, "workspace_id": app.workspace_id, "command": command, "arguments": arguments}
    if operation is not None:
        request["operation_id"] = operation
    if revision is not None:
        request["expected_revision"] = revision
    return app.call(request)


def create(app):
    return invoke(app, "whiteboard.create", {"title": "Testboard", "description": "Gemeinsamer Thread"},
                  operation="create-board", revision=0)["result"]["thread"]


def current(app, identity):
    return app.service.get(identity).revision


def fingerprint(app):
    return GraphChangeService(app.store).status(workspace_id=app.workspace_id)["fingerprint"]


def test_lifecycle_persisted_and_projected_with_conflicts_replay(app):
    thread = create(app)
    identity = thread["id"]
    initial = fingerprint(app)
    assert app.service.get_node("wb-" + identity).kind == "whiteboard"
    assert app.service.allowed_node_transitions("wb-" + identity) == ()
    closed = invoke(app, "whiteboard.close", {"id": identity}, operation="close", revision=current(app, identity))
    assert fingerprint(app) != initial
    assert closed["result"]["thread"]["context"]["extra"]["whiteboard"]["state"] == "closed"
    duplicate = invoke(app, "whiteboard.close", {"id": identity}, operation="close", revision=thread["revision"])
    assert duplicate["duplicate"] is True
    assert duplicate["result_digest"] == closed["result_digest"]
    with pytest.raises(ManagementError, match="changed since"):
        invoke(app, "whiteboard.rename", {"id": identity, "title": "stale"}, operation="stale", revision=thread["revision"])
    with pytest.raises(ManagementError) as conflict:
        invoke(app, "whiteboard.close", {"id": "other"}, operation="close", revision=thread["revision"])
    assert conflict.value.code == "operation_conflict"
    assert app.service.graph(kind="whiteboard")["nodes"][0]["metadata"]["whiteboard_state"] == "closed"
    reopened = ThreadService(store=type(app.store)(app.store.workspace_path))
    assert WhiteboardService(reopened).get(identity)["state"] == "closed"
    invoke(app, "whiteboard.open", {"id": identity}, operation="open", revision=current(app, identity))
    assert app.store.get_current_id() == identity
    invoke(app, "whiteboard.rename", {"id": identity, "title": "Umbenannt"}, operation="rename", revision=current(app, identity))
    assert app.service.get_node("wb-" + identity).title == "Umbenannt"
    invoke(app, "whiteboard.archive", {"id": identity}, operation="archive", revision=current(app, identity))
    assert app.service.get_node("wb-" + identity).status == "archived"
    invoke(app, "whiteboard.unarchive", {"id": identity}, operation="unarchive", revision=current(app, identity))
    assert app.service.get_node("wb-" + identity).metadata["whiteboard_status"] == "open"


def test_edit_keeps_originals_and_closed_blocks_writes(app):
    thread = create(app)
    identity = thread["id"]
    first = app.service.append_whiteboard(identity, actor="Mensch", actor_type="human", entry_type="note", content="Original")["entry"]
    initial = app.store.list_whiteboard(identity)[0].to_dict()
    invoke(app, "whiteboard.edit", {"id": identity, "entry_id": first["id"], "content": "Korrigiert"},
           operation="edit", revision=current(app, identity))
    assert app.store.list_whiteboard(identity)[0].to_dict() == initial
    effective = effective_entries(app.store.list_whiteboard(identity))
    assert len(effective) == 1
    assert effective[0].id == first["id"] and effective[0].content == "Korrigiert"
    invoke(app, "whiteboard.edit", {"id": identity, "entry_id": first["id"], "content": "Erneut"},
           operation="edit-again", revision=current(app, identity))
    assert effective_entries(app.store.list_whiteboard(identity))[0].content == "Erneut"
    assert len(app.store.list_whiteboard(identity)) == 3
    invoke(app, "whiteboard.close", {"id": identity}, operation="close", revision=current(app, identity))
    with pytest.raises(ManagementError) as closed:
        invoke(app, "whiteboard.append", {"id": identity, "actor": "Mensch", "actor_type": "human", "entry_type": "note", "content": "no"},
               operation="blocked-append", revision=current(app, identity))
    assert closed.value.code == "whiteboard_closed"
    assert len(app.store.list_whiteboard(identity)) == 3
    with pytest.raises(ManagementError) as closed_edit:
        invoke(app, "whiteboard.edit", {"id": identity, "entry_id": first["id"], "content": "no"},
               operation="blocked-edit", revision=current(app, identity))
    assert closed_edit.value.code == "whiteboard_closed"


def test_delete_requires_explicit_thread_scope_and_restore_keeps_ids_relations(app):
    thread = create(app)
    identity = thread["id"]
    app.service.set_note("Andere Arbeit bleibt erhalten", identity)
    node = app.service.create_node("project", "Projekt", metadata={"thread_id": identity})
    original = app.service.append_whiteboard(identity, actor="Human", actor_type="human", entry_type="note", content="Beitrag")["entry"]
    relation_id = app.service.relations_for("wb-" + identity)[0].id
    preview = invoke(app, "whiteboard.delete_preview", {"id": identity})["result"]
    assert preview["lifecycle_scope"] == "owning_thread"
    assert original["id"] in preview["references"]["whiteboard"]
    assert node.id in preview["references"]["nodes"]
    with pytest.raises(ManagementError) as no_confirmation:
        invoke(app, "whiteboard.delete", {"id": identity}, operation="no-confirm", revision=current(app, identity))
    assert no_confirmation.value.code == "validation_error"
    assert app.service.get(identity).context.notes == "Andere Arbeit bleibt erhalten"
    result = invoke(app, "whiteboard.delete", {"id": identity, "confirm_thread_move": True}, operation="delete", revision=current(app, identity))["result"]["entry"]
    assert not app.service.graph(kind="whiteboard")["nodes"]
    # Existing trash traffic-light contract remains authoritative and blocks
    # permanent removal while other project nodes still reference the thread.
    purge = TrashService(app.store).purge_preview(result["trash_id"])
    assert "referenced_object" in purge["blockers"]
    invoke(app, "whiteboard.restore", {"trash_id": result["trash_id"], "generation": result["generation"]},
           operation="restore", revision=result["revision"])
    assert app.service.get(identity).context.notes == "Andere Arbeit bleibt erhalten"
    assert app.service.get_node("wb-" + identity).metadata["whiteboard_id"] == identity
    assert app.service.relations_for("wb-" + identity)[0].id == relation_id
    assert app.store.list_whiteboard(identity)[0].to_dict() == original


def test_old_logs_are_projected_without_rewrite_and_untrusted_metadata_is_inert(app):
    thread = app.service.create("Vorhanden")
    assert app.service.graph()["nodes"] == []
    for marker in ({"entry_id": []}, {"entry_id": {}, "previous_entry_id": "x"}, "untrusted"):
        app.service.append_whiteboard(thread.id, actor="Mensch", actor_type="human", entry_type="note",
            content="Alt", metadata={"whiteboard_edit": marker})
    before = app.service.get(thread.id).to_dict()
    entries = app.store.list_whiteboard(thread.id)
    assert len(effective_entries(entries)) == 3
    app.service.create_node("task", "Fremde Metadaten", metadata={"projection": "thread_whiteboard"})
    app.service.create_node("task", "Falscher Eigentümertyp", metadata={"thread_id": []})
    graph = app.service.graph()
    assert any(node["id"] == "wb-" + thread.id for node in graph["nodes"])
    assert app.service.get(thread.id).to_dict() == before
    assert app.store.list_whiteboard(thread.id) == entries
    # Derived display fields and malformed legacy correction markers do not
    # impersonate an edit or prevent a legitimate later correction.
    forged = app.service.append_whiteboard(thread.id, actor="Mensch", actor_type="human", entry_type="note",
        content="Weitere Notiz", metadata={"whiteboard_edited": [], "whiteboard_edit": "inert"})["entry"]
    assert "whiteboard_edited" not in effective_entries(app.store.list_whiteboard(thread.id))[-1].metadata
    invoke(app, "whiteboard.edit", {"id": thread.id, "entry_id": forged["id"], "content": "Legitime Korrektur"},
           operation="correct-legacy-marker", revision=current(app, thread.id))
    assert effective_entries(app.store.list_whiteboard(thread.id))[-1].content == "Legitime Korrektur"


def test_closed_board_still_records_bound_return_events(app):
    from threaddesk.services.whiteboard import append_from_return
    thread = create(app)
    invoke(app, "whiteboard.close", {"id": thread["id"]}, operation="close", revision=thread["revision"])
    before = fingerprint(app)
    revision = current(app, thread["id"])
    result = append_from_return(app.store, {"thread_id": thread["id"], "worker": "codex", "result": "Ergebnis bleibt aufbewahrt", "return_id": "return-closed"})
    assert result["entry"]["content"] == "Ergebnis bleibt aufbewahrt"
    assert WhiteboardService(app.service).get(thread["id"])["state"] == "closed"
    assert current(app, thread["id"]) == revision + 1
    assert fingerprint(app) != before


def test_existing_prefixed_nodes_are_not_shadowed_and_exact_collisions_are_explicit(app):
    from dataclasses import replace
    thread = create(app)
    node = app.service.create_node("task", "Existing imported identity")
    canonical = replace(node, id="wb-external")
    app.store.save_node(canonical)
    assert app.service.get_node(canonical.id).title == canonical.title
    assert app.service.allowed_node_transitions(canonical.id) == ("ready",)
    assert app.service.relations_for(canonical.id) == []
    collision = replace(node, id="wb-" + thread["id"])
    app.store.save_node(collision)
    assert app.service.get_node(collision.id).kind == "task"
    with pytest.raises(ManagementError) as conflict:
        app.service.graph()
    assert conflict.value.code == "graph_projection_conflict"
    assert conflict.value.details["object_id"] == collision.id
    assert app.store.get_node(collision.id).to_dict() == collision.to_dict()


def test_native_whiteboard_owner_results_reconcile_without_repeating_trash(app, monkeypatch):
    from threaddesk.services.commands.reconciliation import verify_owner_result
    thread = create(app)
    move = {"id": thread["id"], "confirm_thread_move": True,
            "operation_id": "native-move", "expected_revision": thread["revision"]}
    moved = WhiteboardService(app.service).delete(move["id"], **{key: value for key, value in move.items() if key != "id"})
    entry = moved["entry"]
    restore = {"trash_id": entry["trash_id"], "generation": entry["generation"],
               "operation_id": "native-restore", "expected_revision": entry["revision"]}
    restored = WhiteboardService(app.service).restore(**restore)
    def forbidden(*args, **kwargs):
        raise AssertionError("Reconciliation must never repeat an owner mutation")
    monkeypatch.setattr(TrashService, "move", forbidden)
    monkeypatch.setattr(TrashService, "restore", forbidden)
    assert verify_owner_result(app.service, "whiteboard.delete", move) == {**moved, "duplicate": True}
    assert verify_owner_result(app.service, "whiteboard.restore", restore) == {**restored, "duplicate": True}
    with pytest.raises(ManagementError) as no_confirmation:
        verify_owner_result(app.service, "whiteboard.delete", {**move, "confirm_thread_move": False})
    assert no_confirmation.value.code == "explicit_confirmation_required"
    with pytest.raises(ManagementError) as conflict:
        verify_owner_result(app.service, "whiteboard.delete", {**move, "id": "wrong"})
    assert conflict.value.code == "operation_conflict"


def test_ui_creation_uses_complete_receipt_for_large_unicode_input(tmp_path, monkeypatch):
    from http_ui_client import UIClient
    from threaddesk.ui.server import create_app
    monkeypatch.setenv("THREADDESK_HOME", str(tmp_path))
    monkeypatch.delenv("THREADDESK_STORAGE", raising=False)
    client = UIClient(create_app())
    response = client.post("/whiteboards", data={"title": "ä" * 6000, "description": "ü" * 6000,
        "operation_id": "long-unicode-create", "expected_revision": "0"}, follow_redirects=False)
    assert response.status_code == 303
    assert "thread=" in response.headers["location"]
    service = ThreadService(JsonStore(tmp_path))
    assert len(service.list()) == 1
    assert len(WhiteboardService(service).list()) == 1
    again = client.post("/whiteboards", data={"title": "ä" * 6000, "description": "ü" * 6000,
        "operation_id": "long-unicode-create", "expected_revision": "0"}, follow_redirects=False)
    assert again.headers["location"] == response.headers["location"]
    assert again.headers["x-threaddesk-duplicate"] == "true"
    assert len(service.list()) == 1
