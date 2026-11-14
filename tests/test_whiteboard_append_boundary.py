"""Append owner boundaries on private stores; no installed profiles or UI."""

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore


@pytest.fixture(params=[JsonStore, SQLiteStore], ids=["json", "sqlite"])
def svc(request, tmp_path):
    service = ThreadService(store=request.param(tmp_path))
    yield service
    if hasattr(service.store, "connection"):
        service.store.connection.close()


def append(svc, thread_id, text="result", key="original-report"):
    return svc.append_whiteboard(
        thread_id,
        actor="Test",
        actor_type="human",
        entry_type="result",
        content=text,
        external_key=key,
    )


def test_revision_failure_leaves_no_entry_or_notification(svc, monkeypatch):
    thread = svc.create("Private transaction test")
    original = svc.get(thread.id).to_dict()
    events = []
    svc.bus.on("whiteboard.appended", lambda *args: events.append(args))

    def failed_revision(_thread):
        raise RuntimeError("injected revision failure")

    monkeypatch.setattr(svc.store, "save_thread", failed_revision)
    with pytest.raises(RuntimeError, match="injected revision failure"):
        append(svc, thread.id)
    assert svc.whiteboard(thread.id) == []
    assert svc.get(thread.id).to_dict() == original
    assert events == []


def test_event_observer_sees_committed_entry_and_revision(svc):
    thread = svc.create("Committed observer")
    prior = svc.get(thread.id).revision
    seen = []

    def observed(_name, payload):
        assert not svc.store.in_transaction
        other = type(svc.store)(svc.store.workspace_path)
        try:
            entries = other.list_whiteboard(thread.id)
            seen.append(
                (
                    payload["id"],
                    [e.id for e in entries],
                    other.get_thread(thread.id).revision,
                )
            )
        finally:
            if hasattr(other, "connection"):
                other.connection.close()

    svc.bus.on("whiteboard.appended", observed)
    result = append(svc, thread.id)
    assert seen == [(result["entry"]["id"], [result["entry"]["id"]], prior + 1)]


def test_existing_owner_boundary_publishes_only_after_commit(svc):
    thread = svc.create("Existing owner")
    events = []
    svc.bus.on("whiteboard.appended", lambda *args: events.append(args))
    with svc.bus.defer_until_commit(), svc.store.transaction():
        result = append(svc, thread.id)
        assert events == []
    assert [e.id for e in svc.whiteboard(thread.id)] == [result["entry"]["id"]]
    assert len(events) == 1


def test_existing_owner_sees_staged_duplicate_and_preserves_ordinal(svc):
    thread = svc.create("Owner duplicate")
    with svc.bus.defer_until_commit(), svc.store.transaction():
        first = append(svc, thread.id)
        duplicate = append(svc, thread.id)
        second = append(svc, thread.id, text="second", key="second-report")
        assert duplicate["duplicate"] is True
        assert duplicate["entry"]["id"] == first["entry"]["id"]
        assert second["entry"]["ordinal"] == first["entry"]["ordinal"] + 1
    assert len(svc.whiteboard(thread.id)) == 2


def test_existing_owner_abort_discards_entry_revision_and_event(svc):
    thread = svc.create("Outer rollback")
    original = svc.get(thread.id).to_dict()
    events = []
    svc.bus.on("whiteboard.appended", lambda *args: events.append(args))
    with (
        pytest.raises(RuntimeError, match="abort outer owner"),
        svc.bus.defer_until_commit(),
        svc.store.transaction(),
    ):
        append(svc, thread.id)
        raise RuntimeError("abort outer owner")
    assert svc.whiteboard(thread.id) == []
    assert svc.get(thread.id).to_dict() == original
    assert events == []
