"""Two real ThreadDesk processes share one room over HTTP.

tests/test_room_sync.py keeps both desks in one process. This test starts
``python -m threaddesk.ui.cli serve`` twice, with two temporary homes.
Playwright is not installed here, and its in-process server cannot isolate
two homes. The forms below are the same posts the desk sends.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

from threaddesk.core.models import WhiteboardEntry
from threaddesk.storage.json_store import JsonStore

ROOT = Path(__file__).resolve().parents[1]
PORT_A = 8765
PORT_B = 8766
URL_A = f"http://127.0.0.1:{PORT_A}"
URL_B = f"http://127.0.0.1:{PORT_B}"


def _port_free(port: int) -> bool:
    """True when nothing is accepting connections. A closed socket may still sit in wait."""
    with socket.socket() as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", port)) != 0


def _wait_until_free(port: int) -> bool:
    deadline = time.time() + 5
    while time.time() < deadline:
        if _port_free(port):
            return True
        time.sleep(0.1)
    return False


def _serve(home: Path, port: int, log_path: Path) -> subprocess.Popen:
    home.mkdir(parents=True, exist_ok=True)
    log = log_path.open("w", encoding="utf-8")
    env = os.environ.copy()
    env["THREADDESK_HOME"] = str(home)
    env["PYTHONPATH"] = str(ROOT / "src")
    env.pop("THREADDESK_STORAGE", None)
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "threaddesk.ui.cli",
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=ROOT,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


def _stop(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    os.killpg(proc.pid, signal.SIGTERM)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait(timeout=5)


def _ready(url: str, proc: subprocess.Popen, log_path: Path) -> None:
    deadline = time.time() + 20
    last = ""
    while time.time() < deadline:
        if proc.poll() is not None:
            pytest.fail(_logs(f"Server endete vor der Bereitschaft: {url}", [log_path]))
        try:
            with urllib.request.urlopen(url + "/", timeout=0.5) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = str(exc)
        time.sleep(0.05)
    pytest.fail(_logs(f"Server nicht bereit: {url} ({last})", [log_path]))


def _logs(message: str, paths: list[Path]) -> str:
    parts = [message]
    for path in paths:
        if path.exists():
            text = path.read_text(encoding="utf-8", errors="replace")
            parts.append(f"--- {path.name} ---\n{text[-4000:]}")
    return "\n".join(parts)


def _request(base: str, path: str, form: dict[str, str] | None = None) -> str:
    data = None if form is None else urllib.parse.urlencode(form).encode()
    request = urllib.request.Request(base + path, data=data, method="POST" if form is not None else "GET")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.read().decode()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        raise AssertionError(f"{base}{path} -> {exc.code}\n{body[:2000]}") from exc


def _field(html: str, name: str) -> str:
    marker = f"{name}>"
    if marker not in html:
        raise AssertionError(f"{name} fehlt\n{html[:1500]}")
    return html.split(marker, 1)[1].split("<", 1)[0].strip()


def _state(html: str) -> str:
    marker = 'data-room-state="'
    if marker not in html:
        raise AssertionError(f"Status fehlt\n{html[:1500]}")
    return html.split(marker, 1)[1].split('"', 1)[0]


def _threads(home: Path) -> list[dict]:
    folder = home / "threads"
    if not folder.exists():
        return []
    return [json.loads(path.read_text(encoding="utf-8")) for path in folder.glob("*.json")]


def _thread_id(home: Path, title: str) -> str:
    for item in _threads(home):
        if item["title"] == title:
            return item["id"]
    raise AssertionError(f"Thread fehlt: {title}")


def _entries(home: Path) -> list[dict]:
    folder = home / "whiteboard"
    if not folder.exists():
        return []
    return [json.loads(path.read_text(encoding="utf-8")) for path in folder.rglob("*.json")]


def _contents(home: Path) -> list[str]:
    return [item["content"] for item in _entries(home)]


def _note(home: Path, title: str) -> str:
    for item in _threads(home):
        if item["title"] == title:
            return item["context"]["notes"]
    return ""


def _plant(home: Path, thread_id: str, room_id: str, content: str, instance_id: str) -> None:
    """The board has no edit route. These are the two local copies."""
    JsonStore(home).append_whiteboard_entry(WhiteboardEntry(
        id="streit0001",
        thread_id=thread_id,
        actor="Ada",
        actor_type="human",
        created_at="2026-10-02T12:00:00+00:00",
        entry_type="note",
        content=content,
        room_id=room_id,
        actor_id="actor-streit",
        instance_id=instance_id,
    ))


def test_two_live_servers_sync_a_room(tmp_path: Path) -> None:
    home_a = tmp_path / "desk-a"
    home_b = tmp_path / "desk-b"
    real_home = Path.home() / ".threaddesk"
    assert home_a.resolve() != home_b.resolve()
    assert real_home.resolve() not in {home_a.resolve(), home_b.resolve()}
    assert str(home_a.resolve()).startswith(str(tmp_path.resolve()))
    if not _wait_until_free(PORT_A) or not _wait_until_free(PORT_B):
        pytest.fail(f"Port {PORT_A} oder {PORT_B} ist belegt")

    log_a = tmp_path / "a.log"
    log_b = tmp_path / "b.log"
    server_a = _serve(home_a, PORT_A, log_a)
    server_b = _serve(home_b, PORT_B, log_b)
    try:
        _ready(URL_A, server_a, log_a)
        _ready(URL_B, server_b, log_b)
        page_a = _request(URL_A, "/")
        page_b = _request(URL_B, "/")
        instance_a = _field(page_a, "data-room-instance").split()[-1]
        instance_b = _field(page_b, "data-room-instance").split()[-1]
        assert instance_a != instance_b

        created = _request(URL_A, "/rooms", {"name": "Werkstatt"})
        assert "Werkstatt" in created
        invited = _request(URL_A, "/rooms/invite", {"role": "member"})
        code = _field(invited, "data-room-code").split()[-1]
        paired = _request(URL_B, "/rooms/join", {"code": code, "base_url": URL_A})
        assert _state(paired) == "connected"
        shown_a = _request(URL_A, "/")
        shown_b = _request(URL_B, "/")
        assert "Werkstatt" in shown_a and "Werkstatt" in shown_b
        assert instance_a in shown_a and instance_b in shown_a
        assert instance_a in shown_b and instance_b in shown_b
        assert "Leitung" in shown_a and "Mitglied" in shown_a

        _request(URL_A, "/threads", {"title": "Seite A", "description": ""})
        _request(URL_B, "/threads", {"title": "Seite B", "description": ""})
        thread_a = _thread_id(home_a, "Seite A")
        thread_b = _thread_id(home_b, "Seite B")
        _request(URL_A, f"/threads/{thread_a}/note", {"text": "privat-notiz-a", "append": ""})
        _request(URL_A, f"/threads/{thread_a}/whiteboard", {
            "actor": "Ada", "actor_type": "human", "entry_type": "note",
            "content": "privat-wb-a", "next_step": "",
        })
        _request(URL_A, f"/threads/{thread_a}/whiteboard", {
            "actor": "Ada", "actor_type": "human", "entry_type": "note",
            "content": "geteilt-a", "next_step": "", "in_room": "1",
        })
        _request(URL_B, "/rooms/sync", {})
        arrived = _contents(home_b)
        assert arrived.count("geteilt-a") == 1
        assert "privat-wb-a" not in arrived
        assert _note(home_a, "Seite A") == "privat-notiz-a"
        assert _note(home_b, "Seite A") == ""
        assert "privat-notiz-a" not in json.dumps(arrived)

        _request(URL_B, f"/threads/{thread_b}/whiteboard", {
            "actor": "Bea", "actor_type": "human", "entry_type": "note",
            "content": "geteilt-b", "next_step": "", "in_room": "1",
        })
        _request(URL_A, "/rooms/sync", {})
        on_a = _contents(home_a)
        assert on_a.count("geteilt-b") == 1
        assert on_a.count("geteilt-a") == 1
        assert on_a.count("privat-wb-a") == 1

        _stop(server_b)
        server_b = None
        _request(URL_A, f"/threads/{thread_a}/whiteboard", {
            "actor": "Ada", "actor_type": "human", "entry_type": "note",
            "content": "offline-a", "next_step": "", "in_room": "1",
        })
        offline = _request(URL_A, "/rooms/sync", {})
        assert _state(offline) == "peer_down"
        assert "Gegenstelle nicht erreichbar" in offline
        assert "offline-a" in _contents(home_a)
        assert "geteilt-a" in _contents(home_a)
        assert "offline-a" not in _contents(home_b)
        server_b = _serve(home_b, PORT_B, log_b)
        _ready(URL_B, server_b, log_b)
        _request(URL_A, "/rooms/sync", {})
        assert "offline-a" in _contents(home_b)
        assert "privat-wb-a" not in _contents(home_b)

        room_id = json.loads((home_a / "rooms.json").read_text(encoding="utf-8"))["current_id"]
        shared_thread = _thread_id(home_a, "Seite A")
        _plant(home_a, shared_thread, room_id, "Fassung A", instance_a)
        _plant(home_b, shared_thread, room_id, "Fassung B", instance_b)
        conflict = _request(URL_A, "/rooms/sync", {})
        assert _state(conflict) == "conflict_kept"
        assert "Konflikt erhalten" in conflict
        _request(URL_B, "/rooms/sync", {})
        _request(URL_A, "/rooms/sync", {})
        kept_a = next(item for item in _entries(home_a) if item["id"] == "streit0001")
        kept_b = next(item for item in _entries(home_b) if item["id"] == "streit0001")
        assert kept_a["content"] == "Fassung A"
        assert kept_b["content"] == "Fassung B"
        blob_a = " ".join(_contents(home_a))
        blob_b = " ".join(_contents(home_b))
        assert "Fassung A" in blob_a and "Fassung B" in blob_a
        assert "Fassung A" in blob_b and "Fassung B" in blob_b
        count_a = len(_entries(home_a))
        count_b = len(_entries(home_b))
        for _ in range(3):
            _request(URL_A, "/rooms/sync", {})
            _request(URL_B, "/rooms/sync", {})
        assert len(_entries(home_a)) == count_a
        assert len(_entries(home_b)) == count_b
        assert _contents(home_a).count("geteilt-a") == 1
        assert _contents(home_b).count("geteilt-b") == 1

        _request(URL_A, "/rooms", {"name": "Leseraum"})
        invited = _request(URL_A, "/rooms/invite", {"role": "read_only"})
        code_ro = _field(invited, "data-room-code").split()[-1]
        joined = _request(URL_B, "/rooms/join", {"code": code_ro, "base_url": URL_A})
        assert "Nur lesen" in joined
        _request(URL_A, f"/threads/{thread_a}/whiteboard", {
            "actor": "Ada", "actor_type": "human", "entry_type": "note",
            "content": "leseraum-von-a", "next_step": "", "in_room": "1",
        })
        _request(URL_B, "/rooms/sync", {})
        assert "leseraum-von-a" in _contents(home_b)
        with pytest.raises(AssertionError, match="-> 403"):
            _request(URL_B, f"/threads/{thread_b}/whiteboard", {
                "actor": "Bea", "actor_type": "human", "entry_type": "note",
                "content": "leseraum-von-b", "next_step": "", "in_room": "1",
            })
        _request(URL_A, "/rooms/sync", {})
        _request(URL_B, "/rooms/sync", {})
        assert "leseraum-von-b" not in _contents(home_a)
        assert "leseraum-von-a" in _contents(home_b)

        _stop(server_a)
        _stop(server_b)
        server_a = _serve(home_a, PORT_A, log_a)
        server_b = _serve(home_b, PORT_B, log_b)
        _ready(URL_A, server_a, log_a)
        _ready(URL_B, server_b, log_b)
        again_a = _request(URL_A, "/")
        again_b = _request(URL_B, "/")
        assert _field(again_a, "data-room-instance").split()[-1] == instance_a
        assert _field(again_b, "data-room-instance").split()[-1] == instance_b
        assert "Leseraum" in again_a and "Werkstatt" in again_a
        assert (home_a / "peers.json").exists() and (home_b / "peers.json").exists()
        before = len(_entries(home_a))
        resumed = _request(URL_A, "/rooms/sync", {})
        assert _state(resumed) != "peer_down"
        assert len(_entries(home_a)) == before
        assert "privat-wb-a" not in _contents(home_b)
        assert "geteilt-a" in _contents(home_b)
        assert _note(home_a, "Seite A") == "privat-notiz-a"
    except Exception as exc:
        pytest.fail(_logs(str(exc), [log_a, log_b]))
    finally:
        _stop(server_a)
        _stop(server_b)
