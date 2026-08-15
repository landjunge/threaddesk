"""Keys must never escape the store directory — not relative, not absolute, not via MCP."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.core.errors import NotFound, ThreadDeskError
from threaddesk.services.mcp import McpBridge
from threaddesk.storage.json_store import JsonStore


@pytest.fixture
def svc(tmp_path: Path) -> ThreadService:
    return ThreadService(store=JsonStore(tmp_path))

TRAVERSAL_KEYS = [
    "../outside",
    "../../deeper",
    "..",
    ".",
    "a/b",
    "a\\b",
    "*",
    "sub/../../outside",
    "",
]


@pytest.mark.parametrize("key", TRAVERSAL_KEYS)
def test_traversal_keys_are_not_found(svc: ThreadService, tmp_path: Path, key: str) -> None:
    svc.create("Echt")
    _plant_outside(tmp_path)
    with pytest.raises(ThreadDeskError):
        svc.get(key)


def test_absolute_path_key_is_not_found(svc: ThreadService, tmp_path: Path) -> None:
    svc.create("Echt")
    target = _plant_outside(tmp_path)
    with pytest.raises(ThreadDeskError):
        svc.get(str(target)[:-5])  # ohne .json, der Store hängt es an


def test_store_get_thread_rejects_traversal(svc: ThreadService, tmp_path: Path) -> None:
    _plant_outside(tmp_path)
    with pytest.raises(NotFound):
        svc.store.get_thread("../outside")


def test_mcp_cannot_read_outside_store(svc: ThreadService, tmp_path: Path) -> None:
    svc.create("Echt")
    _plant_outside(tmp_path)
    bridge = McpBridge(svc)
    for key in ("../outside", "../../deeper"):
        got = bridge.call("get_thread", {"id": key})
        assert got["isError"], f"{key} durfte nicht auflösen"
        assert "LEAKED" not in json.dumps(got, ensure_ascii=False)


def test_no_phantom_thread_files(svc: ThreadService, tmp_path: Path) -> None:
    real = svc.create("Echt")
    _plant_outside(tmp_path)
    for key in ("../outside", "../../deeper"):
        with pytest.raises(ThreadDeskError):
            svc.get(key)
    names = sorted(p.name for p in (tmp_path / "threads").glob("*.json"))
    assert names == [f"{real.id}.json"]


def test_snapshot_id_traversal_blocked(svc: ThreadService, tmp_path: Path) -> None:
    svc.create("Echt")
    svc.snapshot("eins")
    for key in ("../../x", "*", "a/b"):
        with pytest.raises(ThreadDeskError):
            svc.restore(key)


def test_valid_ids_still_work(svc: ThreadService) -> None:
    t = svc.create("Normal")
    assert svc.get(t.id).id == t.id
    assert svc.get(t.id[:6]).id == t.id
    snap = svc.snapshot("s")
    assert svc.restore(snap.id).id == t.id


def _plant_outside(tmp_path: Path) -> Path:
    """A JSON file that looks like a thread, one and two levels above threads/."""
    payload = json.dumps({"id": "pwned", "title": "LEAKED", "context": {"notes": "LEAKED notes"}})
    (tmp_path / "outside.json").write_text(payload, encoding="utf-8")
    (tmp_path.parent / "deeper.json").write_text(payload, encoding="utf-8")
    return tmp_path / "outside.json"
