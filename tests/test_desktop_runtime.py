"""Desktop startup must preserve the workspace and never adopt a foreign server."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import socket

import pytest

from test_desktop_entry import load_desktop_entry
from threaddesk.services.desktop_runtime import desktop_listener, isolated_self_test
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(params=[JsonStore, SQLiteStore], ids=["json", "sqlite"])
def store(request, tmp_path):
    return request.param(tmp_path / "workspace")


def test_desktop_port_is_reserved_and_persistent(store):
    with desktop_listener(store) as listener:
        port = listener.getsockname()[1]
        assert listener.getsockname()[0] == "127.0.0.1"
        with socket.socket() as other:
            with pytest.raises(OSError):
                other.bind(("127.0.0.1", port))
    with desktop_listener(store) as listener:
        assert listener.getsockname()[1] == port


def test_same_workspace_cannot_start_twice(store):
    with desktop_listener(store):
        with pytest.raises(RuntimeError, match="bereits"):
            with desktop_listener(store):
                pytest.fail("Second instance acquired the same workspace")
    with desktop_listener(store):
        pass


def test_foreign_listener_is_not_reused(store):
    with socket.socket() as foreign:
        foreign.bind(("127.0.0.1", 0))
        foreign.listen()
        port = foreign.getsockname()[1]
        store.write_json_artifact("desktop-port.json", {"version": 1, "port": port})
        before = store.artifact_path("desktop-port.json").read_bytes()
        with pytest.raises(RuntimeError, match="belegt"):
            with desktop_listener(store):
                pytest.fail("Attached to an unrelated server")
        assert store.artifact_path("desktop-port.json").read_bytes() == before
        assert foreign.getsockname()[1] == port


@pytest.mark.parametrize("broken", ['{', '{"version":1,"port":true}', '{"version":1,"port":0}'])
def test_broken_port_state_is_not_replaced(store, broken):
    path = store.artifact_path("desktop-port.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(broken, encoding="utf-8")
    with pytest.raises(RuntimeError):
        with desktop_listener(store):
            pytest.fail("Invalid port metadata was accepted")
    assert path.read_text(encoding="utf-8") == broken


def test_self_test_scope_restores_environment_even_on_failure(monkeypatch, tmp_path):
    pretend_user_home = tmp_path / "synthetic-user"
    pretend_user_home.mkdir()
    sentinel = pretend_user_home / "do-not-touch.txt"
    sentinel.write_text("synthetic preserved data", encoding="utf-8")
    monkeypatch.setenv("THREADDESK_HOME", str(pretend_user_home))
    monkeypatch.setenv("THREADDESK_STORAGE", "sqlite")
    with pytest.raises(ValueError):
        with isolated_self_test() as isolated:
            assert isolated != pretend_user_home
            assert os.environ["THREADDESK_HOME"] == str(isolated)
            assert os.environ["THREADDESK_STORAGE"] == "json"
            raise ValueError("Deliberate synthetic interruption")
    assert not isolated.exists()
    assert os.environ["THREADDESK_HOME"] == str(pretend_user_home)
    assert os.environ["THREADDESK_STORAGE"] == "sqlite"
    assert list(pretend_user_home.iterdir()) == [sentinel]
    assert sentinel.read_text(encoding="utf-8") == "synthetic preserved data"


def test_real_package_self_test_never_initializes_user_workspace(monkeypatch, tmp_path):
    pretend_user_home = tmp_path / "untouched"
    monkeypatch.setenv("THREADDESK_HOME", str(pretend_user_home))
    assert load_desktop_entry().self_test() == 0
    assert not pretend_user_home.exists()
    assert os.environ["THREADDESK_HOME"] == str(pretend_user_home)


def test_local_vendor_files_match_reviewed_digests():
    static = ROOT / "src/threaddesk/ui/static"
    expected = {
        "htmx.min.js": "e209dda5c8235479f3166defc7750e1dbcd5a5c1808b7792fc2e6733768fb447",
        "alpine.min.js": "b600e363d99d95444db54acbfb2deffec9ae792aa99a09229bcda078e5b55643",
    }
    manifest = json.loads((static / "ui-vendor.json").read_text(encoding="utf-8"))
    assert {item["file"]: item["sha256"] for item in manifest} == expected
    for filename, digest in expected.items():
        assert hashlib.sha256((static / filename).read_bytes()).hexdigest() == digest
    licenses = (static / "UI-VENDOR-LICENSES.txt").read_text(encoding="utf-8")
    assert "htmx.org 2.0.4" in licenses and "alpinejs 3.14.8" in licenses
    base = (ROOT / "src/threaddesk/ui/templates/base.html").read_text(encoding="utf-8")
    assert 'src="http' not in base
    assert '/static/htmx.min.js' in base and '/static/alpine.min.js' in base
