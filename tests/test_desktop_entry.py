from __future__ import annotations

import importlib.util
from pathlib import Path
import socket


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
