from __future__ import annotations

from pathlib import Path

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.core.errors import InvalidState, SecretRejected
from threaddesk.storage.json_store import JsonStore


@pytest.fixture
def svc(tmp_path: Path) -> ThreadService:
    return ThreadService(store=JsonStore(tmp_path))


def test_create_switch_note_snapshot(svc: ThreadService) -> None:
    a = svc.create("Alpha", "erster gedanke")
    b = svc.create("Beta")
    assert svc.current().id == b.id

    svc.set_note("beta-notiz")
    snap = svc.snapshot("vor-wechsel")
    svc.switch(a.id)
    assert svc.current().id == a.id
    assert svc.current().context.notes == ""

    svc.switch(b.id)
    assert svc.current().context.notes == "beta-notiz"

    svc.set_note("überschrieben")
    svc.restore(snap.id)
    assert svc.current().context.notes == "beta-notiz"


def test_archive_then_delete(svc: ThreadService) -> None:
    t = svc.create("Weg")
    with pytest.raises(InvalidState):
        svc.delete(t.id)
    svc.archive(t.id)
    svc.delete(t.id)
    assert svc.list(include_archived=True) == []


def test_reject_secrets(svc: ThreadService) -> None:
    svc.create("ok")
    with pytest.raises(SecretRejected):
        svc.set_note("api_key=sk-abcdefghijklmnopqrst")


def test_prefix_resolve(svc: ThreadService) -> None:
    t = svc.create("X")
    assert svc.get(t.id[:6]).id == t.id


def test_title_and_index_resolve(svc: ThreadService) -> None:
    svc.create("Gnom Hub")
    b = svc.create("Tollgate Safety")
    assert svc.get("tollgate").id == b.id
    assert svc.get("1").title == "Tollgate Safety"
    assert svc.get("2").title == "Gnom Hub"


def test_append_note_and_files(svc: ThreadService) -> None:
    svc.create("Arbeit")
    svc.set_note("eins")
    svc.set_note("zwei", append=True)
    assert svc.current().context.notes == "eins\nzwei"
    svc.add_file("/tmp/plan.md")
    svc.add_file("/tmp/plan.md")
    assert svc.current().context.files == ["/tmp/plan.md"]
    svc.remove_file("/tmp/plan.md")
    assert svc.current().context.files == []


def test_status_and_unarchive(svc: ThreadService) -> None:
    t = svc.create("S")
    svc.set_status("active")
    assert svc.current().status == "active"
    svc.archive(t.id)
    svc.unarchive(t.id)
    assert svc.get(t.id).status == "paused"


def test_switch_ten_threads_under_two_seconds(svc: ThreadService) -> None:
    import time

    ids = [svc.create(f"T{i}").id for i in range(10)]
    for i, tid in enumerate(ids):
        svc.switch(tid)
        svc.set_note(f"stand {i}")
        svc.snapshot(f"s{i}")
    t0 = time.perf_counter()
    for tid in reversed(ids):
        got = svc.switch(tid)
        assert got.context.notes.startswith("stand")
        assert got.current_snapshot_id
    assert time.perf_counter() - t0 < 2.0
