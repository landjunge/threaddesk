"""Real observer integration, profile selection, privacy and write-free GETs."""

from __future__ import annotations

import builtins
import hashlib
import json
from pathlib import Path

import pytest
from agent_authority.html_report import render_html
from agent_authority.report import build_report
from agent_authority.whiteboard import read_whiteboard
from fastapi.testclient import TestClient

from threaddesk.api.service import ThreadService
from threaddesk.services import authority_preview as preview
from threaddesk.storage.json_store import JsonStore
from threaddesk.ui import server

THREAD = "0123456789ab"
CANARY = "PRIVATE_PROMPT_TASK_ACTOR_PATH_672938"


def tree(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        if p.is_file()
        else "directory"
        for p in root.rglob("*")
    }


def record(root: Path, thread_id: str = THREAD, ordinal: int = 1) -> Path:
    directory = root / "whiteboard" / thread_id
    directory.mkdir(parents=True, exist_ok=True)
    identifier = f"{ordinal:012x}"
    path = directory / f"{identifier}.json"
    path.write_text(
        json.dumps(
            {
                "id": identifier,
                "thread_id": thread_id,
                "ordinal": ordinal,
                "actor": CANARY,
                "actor_type": "codex",
                "entry_type": "claimed",
                "task_id": CANARY,
                "content": CANARY,
                "metadata": {
                    "authenticated": True,
                    "identity": CANARY,
                    "result": CANARY,
                },
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("THREADDESK_HOME", str(tmp_path))
    monkeypatch.delenv("THREADDESK_STORAGE", raising=False)
    return tmp_path


@pytest.fixture
def client(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Observer GET invoked workspace/service/activity")

    monkeypatch.setattr(server, "_svc", forbidden)
    monkeypatch.setattr(server, "_ctx", forbidden)
    monkeypatch.setattr(server, "note_activity", forbidden)
    monkeypatch.setattr(JsonStore, "__init__", forbidden)
    return TestClient(server.create_app())


def test_report_matches_pinned_library_without_writes_or_private_fields(home, client):
    source = record(home)
    before = tree(home)
    response = client.get(f"/threads/{THREAD}/authority")
    assert response.status_code == 200
    assert response.text == render_html(
        build_report(read_whiteboard(home, THREAD), limit=20)
    )
    assert hashlib.sha256(source.read_bytes()).hexdigest() in response.text
    assert THREAD in response.text and "UNBEKANNT" in response.text
    assert CANARY not in response.text and "authenticated" not in response.text
    assert tree(home) == before
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "Content-Security-Policy" in response.text and "<script" not in response.text


def test_selection_does_not_follow_or_change_current_thread(home, client):
    record(home)
    other = "abcdef012345"
    record(home, other, 2)
    (home / "state.json").write_text(json.dumps({"current_thread_id": other}))
    before = tree(home)
    response = client.get(f"/threads/{THREAD}/authority")
    assert THREAD in response.text and other not in response.text
    assert "000000000001" in response.text and "000000000002" not in response.text
    assert tree(home) == before


def test_selected_json_profile_overrides_original_and_environment(
    home, client, monkeypatch
):
    record(home)
    profile = "a" * 32
    target = home / "profiles" / profile
    record(target, ordinal=2)
    (home / "active-profile.json").write_text(
        json.dumps({"name": profile, "backend": "json"})
    )
    monkeypatch.setenv("THREADDESK_STORAGE", "sqlite")
    before = tree(home)
    response = client.get(f"/threads/{THREAD}/authority")
    assert response.status_code == 200
    assert "000000000002" in response.text and "000000000001" not in response.text
    assert profile not in response.text and str(home) not in response.text
    assert tree(home) == before


@pytest.mark.parametrize("selected_profile", [False, True])
def test_sqlite_is_explicitly_unavailable_even_with_json_archive(
    home, client, monkeypatch, selected_profile
):
    record(home)
    if selected_profile:
        name = "b" * 32
        record(home / "profiles" / name)
        (home / "active-profile.json").write_text(
            json.dumps({"name": name, "backend": "sqlite"})
        )
    else:
        monkeypatch.setenv("THREADDESK_STORAGE", "sqlite")
    before = tree(home)
    response = client.get(f"/threads/{THREAD}/authority?lang=en")
    assert response.status_code == 503
    assert "JSON workspaces only" in response.text
    assert "<html" not in response.text and CANARY not in response.text
    assert tree(home) == before


@pytest.mark.parametrize(
    "identifier", ["ABCDEF012345", "too-short", "0123456789ab.json", "<script>"]
)
def test_invalid_identifier_rejected_before_profile_or_service(
    home, client, monkeypatch, identifier
):
    def forbidden(*args):
        raise AssertionError("Profile lookup before identifier validation")

    monkeypatch.setattr(preview, "selected_profile", forbidden)
    response = client.get(f"/threads/{identifier}/authority")
    assert response.status_code == 404
    assert identifier not in response.text and "<script" not in response.text
    assert tree(home) == {}


@pytest.mark.parametrize(
    "condition", ["missing", "wrong-version", "broken-import", "old-python"]
)
def test_optional_package_failure_preserves_default_app(
    home, client, monkeypatch, condition
):
    if condition == "missing":

        def missing(name):
            raise preview.metadata.PackageNotFoundError(CANARY)

        monkeypatch.setattr(preview.metadata, "version", missing)
    elif condition == "wrong-version":
        monkeypatch.setattr(preview.metadata, "version", lambda name: "0.3.0a1")
    elif condition == "old-python":
        monkeypatch.setattr(preview.sys, "version_info", (3, 9))
    else:
        original = builtins.__import__

        def blocked(name, *args, **kwargs):
            if name.startswith("agent_authority"):
                raise ImportError(CANARY)
            return original(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", blocked)
    response = client.get(f"/threads/{THREAD}/authority?lang=en")
    assert response.status_code == 503 and "not set up here yet" in response.text
    assert CANARY not in response.text and str(home) not in response.text
    assert tree(home) == {}


@pytest.mark.parametrize(
    "marker", ["not-json", "[]", '{"name":"../../private","backend":"json"}']
)
def test_invalid_profile_returns_fixed_error_without_workspace_side_effects(
    home, client, marker
):
    (home / "active-profile.json").write_text(marker)
    before = tree(home)
    response = client.get(f"/threads/{THREAD}/authority?lang=en")
    assert response.status_code == 503 and "workspace cannot be read" in response.text
    assert str(home) not in response.text and "private" not in response.text
    assert tree(home) == before


def test_missing_root_is_not_created(home, client, monkeypatch):
    missing = home / "missing"
    monkeypatch.setenv("THREADDESK_HOME", str(missing))
    response = client.get(f"/threads/{THREAD}/authority")
    assert response.status_code == 200 and "unvollständig" in response.text
    assert not missing.exists() and tree(home) == {}


@pytest.mark.parametrize("condition", ["empty", "invalid", "collision", "symlink"])
def test_structural_problems_remain_visible_and_read_only(home, client, condition):
    path = record(home)
    if condition == "empty":
        path.unlink()
    elif condition == "invalid":
        path.write_text("not-json " + CANARY)
    elif condition == "collision":
        other = record(home, ordinal=2)
        value = json.loads(other.read_text())
        value["ordinal"] = 1
        other.write_text(json.dumps(value))
    else:
        target = home / "private.json"
        path.rename(target)
        path.symlink_to(target)
    before = tree(home)
    response = client.get(f"/threads/{THREAD}/authority")
    assert response.status_code == 200
    assert "UNBEKANNT" in response.text
    if condition == "empty":
        assert "Keine Beiträge" in response.text
    else:
        assert "unvollständig" in response.text
    assert CANARY not in response.text and tree(home) == before


def test_link_is_normal_navigation_and_translated(home):
    svc = ThreadService(JsonStore(home))
    thread = svc.create("Local thread")
    client = TestClient(server.create_app())
    for language, label in [
        ("de", "Beobachterbericht öffnen"),
        ("en", "Open observer report (German preview)"),
    ]:
        page = client.get(f"/?lang={language}")
        assert f'href="/threads/{thread.id}/authority"' in page.text
        assert label in page.text
    assert 'hx-get="/threads/' not in page.text
