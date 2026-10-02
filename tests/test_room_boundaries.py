"""Negative probes for the local room protocol. All data is synthetic."""
from __future__ import annotations

import pytest

from threaddesk.core.errors import InvalidState
from threaddesk.services.room_sync import SCHEMA, RoomBook, local_base_url
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore
from test_room_sync import _books, _entry, _pair


@pytest.fixture(params=[JsonStore, SQLiteStore], ids=["json", "sqlite"])
def pair(request, tmp_path):
    left = request.param(tmp_path / "a")
    right = request.param(tmp_path / "b")
    books = _books(left, right)
    room_id = _pair(books)
    return books, room_id, left, right


def bundle(room_id, sender):
    row = _entry("network-test-thread", "network-test-entry", "synthetic contribution", room_id)
    return {
        "schema": SCHEMA, "room_id": room_id, "instance_id": sender,
        "threads": [{"id": row.thread_id, "title": "Synthetic room thread"}],
        "entries": [row.to_dict()],
    }


def replace_pull(book, packet):
    original = book.transport
    def transport(url, payload, headers):
        if url.endswith("/pull"):
            return packet
        return original(url, payload, headers)
    book.transport = transport


def test_pull_is_bound_to_requested_room(pair):
    books, room_id, left, _ = pair
    other = books["a"].create_room("Other local room")["id"]
    books["a"].select_room(room_id)
    replace_pull(books["a"], bundle(other, books["b"].instance_id()))
    assert books["a"].sync()["ok"] is False
    assert left.list_threads(include_archived=True) == []


def test_pull_is_bound_to_paired_instance(pair):
    books, room_id, left, _ = pair
    replace_pull(books["a"], bundle(room_id, "unrelated-instance"))
    assert books["a"].sync()["ok"] is False
    assert left.list_threads(include_archived=True) == []


@pytest.mark.parametrize("store_type", [JsonStore, SQLiteStore])
def test_read_only_peer_cannot_publish_via_pull(store_type, tmp_path):
    left, right = store_type(tmp_path / "a"), store_type(tmp_path / "b")
    books = _books(left, right)
    room_id = _pair(books, role="read_only")
    replace_pull(books["a"], bundle(room_id, books["b"].instance_id()))
    assert books["a"].sync()["ok"] is False
    assert left.list_threads(include_archived=True) == []


def test_push_sender_must_match_authenticated_instance(pair):
    books, room_id, left, _ = pair
    token = books["a"]._peers_for(room_id)[0]["token"]
    with pytest.raises(InvalidState):
        books["a"].serve_push(books["b"].instance_id(), token, bundle(room_id, "forged-sender"))
    assert left.list_threads(include_archived=True) == []


def test_unknown_room_is_not_imported(pair):
    books, _, left, _ = pair
    with pytest.raises(InvalidState):
        books["a"].apply_bundle(bundle("unknown-room", books["b"].instance_id()))
    assert left.list_threads(include_archived=True) == []


def test_invalid_entry_rejects_entire_packet_before_writing(pair):
    books, room_id, left, _ = pair
    packet = bundle(room_id, books["b"].instance_id())
    packet["entries"].append({"id": "bad", "thread_id": "bad", "room_id": "another-room"})
    with pytest.raises(InvalidState):
        books["a"].apply_bundle(packet)
    assert left.list_threads(include_archived=True) == []


def test_invalid_invitation_role_is_not_promoted_to_member(pair):
    books, _, _, _ = pair
    with pytest.raises(InvalidState):
        books["a"].invite("read-only-typo")


def test_unicode_invitation_is_rejected_without_type_error(pair):
    books, _, _, _ = pair
    code = books["a"].invite()
    with pytest.raises(InvalidState):
        books["a"].accept("é" * len(code), "other-guest", "http://127.0.0.1:8767")


def test_corrupt_room_state_is_not_silently_overwritten(tmp_path):
    store = JsonStore(tmp_path)
    book = RoomBook(store)
    book.create_room("Existing")
    path = store.artifact_path("rooms.json")
    broken = '{"version":1,"rooms":['
    path.write_text(broken, encoding="utf-8")
    with pytest.raises(InvalidState):
        book.create_room("Must not replace the old room")
    assert path.read_text(encoding="utf-8") == broken


@pytest.mark.parametrize("address", [
    "http://127.0.0.1:invalid", "http://127.0.0.1:99999", "http://127.0.0.1:0",
    "http://[broken:8765", "http://169.254.169.254:80", "http://127.0.0.1:8765\n",
])
def test_invalid_network_addresses_fail_as_domain_errors(address):
    with pytest.raises(InvalidState):
        local_base_url(address)
