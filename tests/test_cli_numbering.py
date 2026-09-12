"""Die Nummern in `td list` müssen dasselbe bedeuten wie in `td switch <n>`.

Regressionstest. Vorher nummerierte `td list --all` inklusive der archivierten
Threads, während `td switch <n>` immer gegen die nicht archivierten auflöste.
Wer eine Nummer aus der Liste abschrieb, landete stillschweigend beim falschen
Thread — oder bekam "nicht gefunden" für eine Zeile, die er vor sich sah.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.core import i18n
from threaddesk.storage.json_store import JsonStore
from threaddesk.ui import cli

# "  2. 020ae30861d3  [idea    ]  Alpha  snap=-"  → Nummer und Kennung.
ROW = re.compile(r"^(?P<mark>.)\s*(?:(?P<number>\d+)\.)?\s+(?P<id>[0-9a-f]{12})\s")


@pytest.fixture()
def svc(tmp_path: Path) -> ThreadService:
    return ThreadService(store=JsonStore(tmp_path))


def _rows(output: str) -> list[tuple[int | None, str]]:
    """Was der Nutzer vor sich sieht: je Zeile die Nummer und die Kennung."""
    found = []
    for line in output.splitlines():
        match = ROW.match(line)
        if match:
            number = match.group("number")
            found.append((int(number) if number else None, match.group("id")))
    return found


def _list(svc: ThreadService, monkeypatch, capsys, *, include_archived: bool) -> str:
    monkeypatch.setattr(cli, "_svc", lambda: svc)
    args = argparse.Namespace(all=include_archived, lang=i18n.DEFAULT_LANGUAGE)
    assert cli.cmd_list(args) == 0
    return capsys.readouterr().out


def _mixed(svc: ThreadService) -> dict[str, str]:
    """Drei Threads, der mittlere archiviert — der Fall aus dem Fehlerbericht."""
    alpha = svc.create("Alpha")
    beta = svc.create("Beta")
    gamma = svc.create("Gamma")
    svc.archive(beta.id)
    return {"alpha": alpha.id, "beta": beta.id, "gamma": gamma.id}


def test_every_printed_number_leads_to_its_own_line(svc, monkeypatch, capsys) -> None:
    """Der eigentliche Test: eine Nummer abschreiben und dort landen."""
    _mixed(svc)
    for include_archived in (False, True):
        rows = _rows(_list(svc, monkeypatch, capsys, include_archived=include_archived))
        numbered = [(number, thread_id) for number, thread_id in rows if number is not None]
        assert numbered, f"keine nummerierte Zeile (--all={include_archived})"
        for number, thread_id in numbered:
            landed = svc.switch(str(number))
            assert landed.id == thread_id, (
                f"Zeile {number} zeigt {thread_id}, aber `td switch {number}` "
                f"führt zu {landed.id}")


def test_archived_threads_carry_no_number(svc, monkeypatch, capsys) -> None:
    ids = _mixed(svc)
    rows = _rows(_list(svc, monkeypatch, capsys, include_archived=True))
    numbers = dict((thread_id, number) for number, thread_id in rows)
    assert numbers[ids["beta"]] is None, "archiviert, darf keine Nummer tragen"
    assert numbers[ids["alpha"]] is not None
    assert numbers[ids["gamma"]] is not None


def test_numbers_are_the_same_with_and_without_archive(svc, monkeypatch, capsys) -> None:
    """--all darf die Nummern nicht verschieben, nur Zeilen ergänzen."""
    _mixed(svc)
    plain = [(n, i) for n, i in _rows(_list(svc, monkeypatch, capsys, include_archived=False))
             if n is not None]
    with_archive = [(n, i) for n, i in _rows(_list(svc, monkeypatch, capsys, include_archived=True))
                    if n is not None]
    assert plain == with_archive


def test_archived_thread_stays_reachable_by_title(svc) -> None:
    """Keine Nummer heißt nicht unerreichbar."""
    ids = _mixed(svc)
    assert svc.switch("Beta").id == ids["beta"]
    assert svc.switch(ids["beta"]).id == ids["beta"]


def test_unknown_number_is_refused_instead_of_guessing(svc) -> None:
    from threaddesk.core.errors import NotFound

    _mixed(svc)
    with pytest.raises(NotFound):
        svc.switch("99")


def test_the_reported_case(svc, monkeypatch, capsys) -> None:
    """Der gemeldete Fall, wörtlich: drei Threads, der mittlere archiviert.

    Vorher stand Alpha in `td list --all` an Position 3, `td switch 3` gab aber
    "nicht gefunden" — und `td switch 2` landete auf Alpha statt auf Gamma.
    """
    ids = _mixed(svc)
    rows = _rows(_list(svc, monkeypatch, capsys, include_archived=True))
    shown = {thread_id: number for number, thread_id in rows}

    assert shown[ids["beta"]] is None
    assert svc.switch(str(shown[ids["gamma"]])).id == ids["gamma"]
    assert svc.switch(str(shown[ids["alpha"]])).id == ids["alpha"]
    # Es gibt zwei nicht archivierte Threads, also keine Position 3.
    assert 3 not in {number for number, _ in rows if number is not None}
