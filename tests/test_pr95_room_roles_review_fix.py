"""Authenticated read-only room peers cannot publish lifecycle changes."""
from copy import deepcopy

import pytest
from test_room_sync import _books, _entry, _pair

from threaddesk.core.models import Thread, new_thread
from threaddesk.services.trash import TrashService
from threaddesk.services.trash_sync import (
    ROOM_SCHEMA,
    content_digest,
    export_room_lifecycle,
)
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore


@pytest.fixture(params=[JsonStore, SQLiteStore], ids=["json", "sqlite"])
def desks(tmp_path, request):
    values = request.param(tmp_path / "owner"), request.param(tmp_path / "peer")
    yield values
    for store in values:
        if isinstance(store, SQLiteStore):
            store.connection.close()


def shared_thread(desks, role):
    owner, peer = desks
    books = _books(owner, peer)
    room_id = _pair(books, role=role)
    thread = new_thread("Retained owner thread")
    entry = _entry(thread.id, "shared-owner-entry", "Retained room bytes", room_id)
    for store in desks:
        store.save_thread(Thread.from_dict(thread.to_dict()))
        store.append_whiteboard_entry(deepcopy(entry))
    assert books["a"].sync()["ok"]
    assert peer.get_thread(thread.id).title == thread.title
    assert content_digest(owner, thread.id, room_id) == content_digest(peer, thread.id, room_id)
    return books, room_id, thread.id


def owner_data_bytes(store):
    # sync() may update its existing room connection status; no thread, board,
    # SQLite payload, lifecycle, conflict or management receipt may change.
    return {path.relative_to(store.root).as_posix(): path.read_bytes()
            for path in store.root.rglob("*")
            if path.is_file() and path != store.artifact_path("rooms.json")}


@pytest.mark.parametrize("incoming_state", ["trashed", "restored", "purged"])
def test_read_only_lifecycle_pull_is_rejected_before_apply_without_owner_writes(desks, monkeypatch, incoming_state):
    owner, peer = desks
    books, room_id, identity = shared_thread(desks, "read_only")
    TrashService(peer).move(kind="thread", object_id=identity,
                            expected_revision=peer.get_thread(identity).revision,
                            operation_id="local-peer-trash")
    lifecycle = export_room_lifecycle(peer, room_id)
    assert len(lifecycle) == 1
    lifecycle[0]["state"] = incoming_state
    malicious = {"schema": ROOM_SCHEMA, "room_id": room_id,
                 "instance_id": books["b"].instance_id(), "entries": [], "threads": [],
                 "lifecycle": lifecycle}
    original_transport = books["a"].transport
    original_apply = books["a"].apply_bundle
    applied = []

    def transport(url, payload, headers):
        if url.endswith("/pull"):
            return deepcopy(malicious)
        return original_transport(url, payload, headers)

    def audited_apply(bundle):
        applied.append(bundle)
        return original_apply(bundle)

    monkeypatch.setattr(books["a"], "transport", transport)
    monkeypatch.setattr(books["a"], "apply_bundle", audited_apply)
    before = owner_data_bytes(owner)
    for _ in range(2):
        assert books["a"].sync() == {"ok": False, "state": "peer_down", "conflicts": 0}
        assert applied == []
        assert owner_data_bytes(owner) == before
        assert not owner.object_in_trash("thread", identity)
        assert owner.list_trash_entries() == []
        assert owner.list_management_operations() == []
        assert owner.get_thread(identity).title == "Retained owner thread"
        assert owner.list_whiteboard(identity)[0].content == "Retained room bytes"


@pytest.mark.parametrize("schema", ["threaddesk.room.v1", ROOM_SCHEMA])
def test_empty_read_only_pull_remains_allowed_and_preserves_owner_bytes(desks, monkeypatch, schema):
    owner, _peer = desks
    books, _room_id, identity = shared_thread(desks, "read_only")
    original_transport = books["a"].transport

    def transport(url, payload, headers):
        packet = original_transport(url, payload, headers)
        if url.endswith("/pull"):
            packet["schema"] = schema
            if schema == ROOM_SCHEMA:
                packet["lifecycle"] = []
        return packet

    monkeypatch.setattr(books["a"], "transport", transport)
    before = owner_data_bytes(owner)
    for _ in range(2):
        assert books["a"].sync() == {"ok": True, "state": "synced", "conflicts": 0}
        assert owner_data_bytes(owner) == before
        assert owner.get_thread(identity).title == "Retained owner thread"


@pytest.mark.parametrize("publisher", ["owner", "member"])
def test_allowed_publisher_lifecycle_only_trash_restore_and_replay(desks, publisher):
    books, room_id, identity = shared_thread(desks, "read_only" if publisher == "owner" else "member")
    source_key, target_key = ("a", "b") if publisher == "owner" else ("b", "a")
    source, target = books[source_key].store, books[target_key].store
    entry = TrashService(source).move(kind="thread", object_id=identity,
                                      expected_revision=source.get_thread(identity).revision,
                                      operation_id="publisher-trash")["entry"]
    packet = books[source_key].export_bundle(room_id)
    assert packet["schema"] == ROOM_SCHEMA and packet["entries"] == [] and packet["lifecycle"]
    assert books[target_key].sync()["ok"]
    assert target.object_in_trash("thread", identity)
    before = owner_data_bytes(target)
    assert books[target_key].sync()["ok"]
    assert owner_data_bytes(target) == before
    assert target.get_object_lifecycle("thread", identity)["generation"] == 1

    TrashService(source).restore(trash_id=entry["trash_id"], generation=1,
                                 expected_revision=1, operation_id="publisher-restore")
    assert books[target_key].sync()["ok"]
    assert target.get_thread(identity).title == "Retained owner thread"
    assert target.list_whiteboard(identity)[0].id == "shared-owner-entry"
    restored = target.get_object_lifecycle("thread", identity)
    assert restored["state"] == "restored" and restored["generation"] == 1
    assert books[target_key].sync()["ok"]
    assert target.get_object_lifecycle("thread", identity) == restored
