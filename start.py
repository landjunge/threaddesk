#!/usr/bin/env python3
"""Install ThreadDesk locally when needed, then open its local UI."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import webbrowser

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
MARKER = VENV / ".threaddesk-ready"


def open_browser_url(url: str) -> bool:
    """Use Launch Services on macOS; Python's AppleScript hook can be broken."""
    if sys.platform == "darwin":
        try:
            return subprocess.call(["/usr/bin/open", url]) == 0
        except OSError:
            return False
    return webbrowser.open(url)


def open_installer() -> None:
    """Show a friendly first-start screen instead of a terminal-only install."""
    installer = ROOT / "installer.html"
    if installer.exists():
        open_browser_url(installer.as_uri())


def venv_python() -> Path:
    if os.name == "nt":
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def project_fingerprint() -> str:
    return hashlib.sha256((ROOT / "pyproject.toml").read_bytes()).hexdigest()


def ensure_installed() -> Path:
    if sys.version_info < (3, 9):
        raise RuntimeError("ThreadDesk benötigt Python 3.9 oder neuer.")
    python = venv_python()
    fingerprint = project_fingerprint()
    if not python.exists():
        print("ThreadDesk wird beim ersten Start eingerichtet …")
        subprocess.check_call([sys.executable, "-m", "venv", str(VENV)])
    if not MARKER.exists() or MARKER.read_text(encoding="utf-8").strip() != fingerprint:
        print("Installationshilfe wird aktualisiert …")
        subprocess.check_call(
            [str(python), "-m", "pip", "install", "--upgrade", "pip>=21.3"], cwd=ROOT
        )
        print("Benötigte Bestandteile werden installiert …")
        subprocess.check_call(
            [str(python), "-m", "pip", "install", "-e", ".[ui]"], cwd=ROOT
        )
        MARKER.write_text(fingerprint + "\n", encoding="utf-8")
    return python


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ThreadDesk einfach starten")
    parser.add_argument("--install-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        if not args.install_only:
            open_installer()
        python = ensure_installed()
        if args.install_only:
            print("ThreadDesk ist startbereit.")
            return 0
        print("ThreadDesk startet. Der Browser öffnet sich gleich …")
        return subprocess.call(
            [str(python), "-m", "threaddesk.ui.cli", "serve", "--open"], cwd=ROOT
        )
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print("ThreadDesk konnte nicht eingerichtet oder gestartet werden.", file=sys.stderr)
        print(f"Grund: {exc}", file=sys.stderr)
        print("Bitte kopiere diese Meldung vollständig in ein GitHub-Issue.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
