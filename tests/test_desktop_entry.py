from __future__ import annotations

import importlib.util
from pathlib import Path
import socket
import sys
from types import SimpleNamespace
from urllib.request import Request


def test_desktop_window_allows_verified_backup_download(monkeypatch, tmp_path):
    """Exercise the native entry point and real server with a headless window."""
    desktop = load_desktop_entry()
    monkeypatch.setenv("THREADDESK_HOME", str(tmp_path / "workspace"))
    monkeypatch.setenv("THREADDESK_STORAGE", "json")
    monkeypatch.setattr(sys, "argv", ["ThreadDesk"])
    from threaddesk.ui.server import _svc
    from threaddesk.storage.portable_backup import restore_backup
    from threaddesk.storage.json_store import JsonStore
    from threaddesk.api.service import ThreadService

    service = _svc()
    thread = service.create("Desktop-Sicherung")
    service.set_note("Native Downloads müssen funktionieren", thread.id)
    window = {}
    webview = SimpleNamespace(settings={"ALLOW_DOWNLOADS": False})

    def create_window(title, url=None, **kwargs):
        assert title == "ThreadDesk", kwargs
        window["url"] = url

    def start():
        # A plain browser test cannot detect a disabled native download handler.
        assert webview.settings["ALLOW_DOWNLOADS"] is True
        request = Request(window["url"] + "data/download", data=b"", method="POST")
        with desktop.urlopen(request) as response:
            assert response.headers["Content-Type"] == "application/zip"
            backup = response.read()
        restored = restore_backup(backup, tmp_path / "separate-installation")
        assert ThreadService(JsonStore(restored)).current().context.notes == (
            "Native Downloads müssen funktionieren"
        )

    webview.create_window = create_window
    webview.start = start
    monkeypatch.setitem(sys.modules, "webview", webview)
    assert desktop.main() == 0
    assert service.current().context.notes == "Native Downloads müssen funktionieren"


def load_desktop_entry():
    path = Path(__file__).parents[1] / "packaging" / "desktop_entry.py"
    spec = importlib.util.spec_from_file_location("desktop_entry", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_free_port_is_local_and_available() -> None:
    desktop = load_desktop_entry()
    port = desktop.free_port()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", port))


def test_wait_until_ready_accepts_success(monkeypatch) -> None:
    desktop = load_desktop_entry()

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

    monkeypatch.setattr(desktop, "urlopen", lambda *_args, **_kwargs: Response())
    desktop.wait_until_ready("http://127.0.0.1:12345", timeout=0.01)


def test_self_test_without_console_streams_preserves_user_home(monkeypatch, tmp_path):
    desktop = load_desktop_entry()
    untouched = tmp_path / "synthetic-existing-user-setting"
    monkeypatch.setenv("THREADDESK_HOME", str(untouched))
    with monkeypatch.context() as console:
        console.setattr(sys, "stdin", None)
        console.setattr(sys, "stdout", None)
        console.setattr(sys, "stderr", None)
        result = desktop.self_test()
    assert result == 0
    assert not untouched.exists()
