#!/usr/bin/env python3
"""Open this checkout in the browser, after backing up the local workspace."""
from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
import webbrowser

from start import ROOT, ensure_installed

URL = "http://127.0.0.1:8765/"


def require_stopped() -> None:
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", 8765))
    root = Path(os.environ.get("THREADDESK_HOME") or Path.home() / ".threaddesk")
    marker = root / "desktop-port.json"
    if marker.exists():
        import json
        try:
            port = int(json.loads(marker.read_text())["port"])
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                raise RuntimeError("Die ThreadDesk-App läuft noch. Bitte vollständig beenden.")
        except (ValueError, KeyError, TypeError, OSError):
            pass


def backup_workspace() -> Path | None:
    root = Path(os.environ.get("THREADDESK_HOME") or Path.home() / ".threaddesk")
    if not root.exists():
        return None
    destination = root.parent / (root.name + "-vor-browser-update-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
    shutil.copytree(root, destination, symlinks=True)
    return destination


def main() -> int:
    child = None
    try:
        print("ThreadDesk – neuer Browser-Stand. Bitte dieses Fenster geöffnet lassen.", flush=True)
        require_stopped()
        python = ensure_installed()
        require_stopped()
        backup = backup_workspace()
        if backup:
            print("Datenkopie vor dem Start: " + str(backup), flush=True)
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(ROOT / "src")
        child = subprocess.Popen(
            [str(python), "-m", "threaddesk.ui.cli", "serve"],
            cwd=ROOT, env=environment,
        )
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if child.poll() is not None:
                raise RuntimeError("Der Server konnte nicht starten. Die Meldung steht darüber.")
            try:
                with urllib.request.urlopen(URL, timeout=1) as response:
                    ready = response.status == 200
                if ready and child.poll() is None:
                    print("ThreadDesk ist bereit: " + URL, flush=True)
                    webbrowser.open(URL + "?lang=de&stand=bce7828")
                    return child.wait()
            except (OSError, urllib.error.URLError):
                pass
            time.sleep(0.2)
        raise RuntimeError("Der Start dauert zu lange. Bitte die Meldung darüber prüfen.")
    except KeyboardInterrupt:
        return 0
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print("Start nicht möglich: " + str(error), flush=True)
        print("Falls ThreadDesk noch läuft: App bzw. bisherigen Server beenden und erneut starten.", flush=True)
        return 1
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == "__main__":
    raise SystemExit(main())
