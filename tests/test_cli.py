from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.storage.json_store import JsonStore
from threaddesk.ui import cli


@pytest.fixture
def svc(tmp_path: Path) -> ThreadService:
    return ThreadService(store=JsonStore(tmp_path))


def test_numbered_skips_archived_and_matches_resolve(svc: ThreadService) -> None:
    """`td list --all` must number threads exactly like `td switch <n>` resolves them.

    Regression test: archived threads used to shift the numbering shown by
    `--all` out of sync with ThreadService._resolve (which only indexes the
    non-archived list). `td switch <n>` on a number copied from `--all`
    output could silently land on the wrong thread.
    """
    a = svc.create("Alpha")
    b = svc.create("Beta")
    svc.archive(b.id)
    c = svc.create("Gamma")

    all_rows = svc.list(include_archived=True)
    active_ids = [t.id for t in svc.list(include_archived=False)]
    numbered = cli._numbered(all_rows, active_ids)

    by_id = {t.id: index for t, index in numbered}
    assert by_id[b.id] is None  # archived thread never gets a number
    assert by_id[a.id] is not None
    assert by_id[c.id] is not None

    # Whatever number is shown for a thread must resolve back to that thread.
    for t, index in numbered:
        if index is None:
            continue
        assert svc.switch(str(index)).id == t.id


def test_cmd_list_all_prints_without_crashing(
    svc: ThreadService, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    svc.create("Alpha")
    archived = svc.create("Beta")
    svc.archive(archived.id)
    svc.create("Gamma")

    monkeypatch.setattr(cli, "_svc", lambda: svc)
    assert cli.cmd_list(argparse.Namespace(all=True)) == 0
    out = capsys.readouterr().out
    assert "Alpha" in out
    assert "Beta" in out
    assert "Gamma" in out
