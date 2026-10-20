from __future__ import annotations

import importlib.util
from pathlib import Path
import socket
import sys

import pytest


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


def test_startup_checks_fast_asset_without_rendering_slow_home(monkeypatch, tmp_path):
    import asyncio

    from fastapi import FastAPI, Response
    from threaddesk.ui import server

    desktop = load_desktop_entry()
    monkeypatch.setenv("THREADDESK_HOME", str(tmp_path / "synthetic-workspace"))
    app = FastAPI()
    calls = []

    @app.get("/")
    async def slow_home():
        calls.append("home")
        await asyncio.sleep(1)
        return Response("synthetic slow workspace")

    @app.get("/static/style.css")
    async def fast_asset():
        calls.append("asset")
        return Response("body{}", media_type="text/css")

    monkeypatch.setattr(server, "create_app", lambda: app)
    original_wait = desktop.wait_until_ready
    monkeypatch.setattr(desktop, "wait_until_ready", lambda url, thread=None:
                        original_wait(url, timeout=0.8, thread=thread))
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        with desktop.running_server(listener) as url:
            assert calls == ["asset"]
            # The same real HTTP server cannot deliver its home inside the
            # readiness request deadline; successful startup did not need it.
            with pytest.raises(TimeoutError):
                desktop.urlopen(url + "/", timeout=0.05)
            assert calls == ["asset", "home"]


def test_readiness_refuses_a_stopped_server(monkeypatch):
    desktop = load_desktop_entry()

    class Stopped:
        def is_alive(self):
            return False

    def unexpected_probe(*args, **kwargs):
        pytest.fail("A dead server must fail before any HTTP readiness probe")

    monkeypatch.setattr(desktop, "urlopen", unexpected_probe)
    with pytest.raises(RuntimeError, match="unerwartet beendet"):
        desktop.wait_until_ready("http://127.0.0.1:12345/static/style.css", thread=Stopped())
