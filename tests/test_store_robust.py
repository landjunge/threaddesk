"""Store robustness: a corrupt file must never brick a listing command."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.core.errors import ThreadDeskError
from threaddesk.storage.json_store import JsonStore
from threaddesk.ui import cli


@pytest.fixture
def svc(tmp_path: Path) -> ThreadService:
    return ThreadService(store=JsonStore(tmp_path))


# --- corrupt files -----------------------------------------------------------


def test_corrupt_file_is_skipped_not_fatal(svc: ThreadService, tmp_path: Path) -> None:
    svc.create("Gut")
    (tmp_path / "threads" / "zz_corrupt.json").write_text("{bad", encoding="utf-8")
    rows = svc.list()
    assert [t.title for t in rows] == ["Gut"]
    assert svc.store.last_skipped == ["zz_corrupt.json"]


def test_missing_keys_file_is_skipped(svc: ThreadService, tmp_path: Path) -> None:
    svc.create("Gut")
    (tmp_path / "threads" / "zz_nokeys.json").write_text('{"foo": 1}', encoding="utf-8")
    rows = svc.list()
    assert [t.title for t in rows] == ["Gut"]
    assert svc.store.last_skipped == ["zz_nokeys.json"]


def test_corrupt_file_is_not_deleted(svc: ThreadService, tmp_path: Path) -> None:
    broken = tmp_path / "threads" / "zz_corrupt.json"
    broken.write_text("{bad", encoding="utf-8")
    svc.list()
    assert broken.is_file(), "kaputte Dateien werden übersprungen, nicht gelöscht"


def test_direct_get_of_corrupt_raises_threaddeskerror(svc: ThreadService, tmp_path: Path) -> None:
    (tmp_path / "threads" / "aabbccddeeff.json").write_text("{bad", encoding="utf-8")
    with pytest.raises(ThreadDeskError):
        svc.store.get_thread("aabbccddeeff")


def test_dashboard_survives_corrupt_store(svc: ThreadService, tmp_path: Path) -> None:
    svc.create("Bleibt")
    (tmp_path / "threads" / "zz_corrupt.json").write_text("nicht json", encoding="utf-8")
    board = svc.dashboard()
    assert board["counts"]["idea"] == 1


def test_bad_status_falls_back_to_idea(svc: ThreadService, tmp_path: Path) -> None:
    t = svc.create("Status kaputt")
    path = tmp_path / "threads" / f"{t.id}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["status"] = "erfunden"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert svc.get(t.id).status == "idea"


def test_cli_list_survives_corrupt_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("threaddesk.storage.json_store.DEFAULT_ROOT", tmp_path)
    assert cli.main(["new", "Heil"]) == 0
    (tmp_path / "threads" / "zz_corrupt.json").write_text("{bad", encoding="utf-8")
    capsys.readouterr()
    assert cli.main(["list"]) == 0
    out = capsys.readouterr()
    assert "Heil" in out.out
    assert "zz_corrupt.json" in out.err
    assert "Traceback" not in out.err
