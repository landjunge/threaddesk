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
