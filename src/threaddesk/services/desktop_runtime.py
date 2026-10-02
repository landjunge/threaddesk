"""Desktop-only lifecycle helpers. Local runtime state never belongs in Git."""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import tempfile
from typing import Iterator


@contextmanager
def isolated_self_test() -> Iterator[Path]:
    """A packaged diagnostic must not open the caller's real workspace."""
    names = ("THREADDESK_HOME", "THREADDESK_STORAGE")
    previous = {name: os.environ.get(name) for name in names}
    with tempfile.TemporaryDirectory(prefix="threaddesk-selftest-") as folder:
        os.environ["THREADDESK_HOME"] = folder
        os.environ["THREADDESK_STORAGE"] = "json"
        try:
            yield Path(folder)
        finally:
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value


def _lock(handle) -> None:
    if os.name == "nt":
        import msvcrt
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


@contextmanager
def desktop_listener(store) -> Iterator[socket.socket]:
    """Keep the address stable across restarts and never attach to a foreign app.

    The lock covers first allocation too, so two simultaneous launches cannot
    create different servers for one workspace. Binding happens before any HTTP
    readiness probe. A occupied saved port is an error, never a silent re-pair.
    """
    lock_path = store.artifact_path("desktop.lock")
    state_path = store.artifact_path("desktop-port.json")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        try:
            _lock(handle)
        except OSError as exc:
            raise RuntimeError("ThreadDesk läuft für diesen Arbeitsbereich bereits. Öffne das vorhandene Fenster.") from exc
        try:
            saved = json.loads(state_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            saved = None
        except (OSError, ValueError, UnicodeError) as exc:
            raise RuntimeError("Die gespeicherte ThreadDesk-Adresse ist beschädigt. Sie wurde nicht überschrieben.") from exc
        port = 0
        if saved is not None:
            if (not isinstance(saved, dict) or saved.get("version") != 1
                or type(saved.get("port")) is not int or not 1 <= saved["port"] <= 65535):
                raise RuntimeError("Die gespeicherte ThreadDesk-Adresse ist ungültig. Sie wurde nicht überschrieben.")
            port = saved["port"]
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            if os.name != "nt":
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            elif hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            try:
                listener.bind(("127.0.0.1", port))
            except OSError as exc:
                raise RuntimeError("Die lokale ThreadDesk-Adresse ist belegt. Beende die andere Anwendung und starte ThreadDesk erneut.") from exc
            listener.listen(128)
            if saved is None:
                store.write_json_artifact("desktop-port.json", {
                    "version": 1, "port": listener.getsockname()[1],
                })
            yield listener
