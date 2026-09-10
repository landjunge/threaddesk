#!/usr/bin/env python3
"""Install ThreadDesk locally when needed, then open its local UI."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
MARKER = VENV / ".threaddesk-ready"


def venv_python() -> Path:
    if os.name == "nt":
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def project_fingerprint() -> str:
    return hashlib.sha256((ROOT / "pyproject.toml").read_bytes()).hexdigest()


def ensure_installed() -> Path:
    python = venv_python()
    fingerprint = project_fingerprint()
    if not python.exists():
        print("ThreadDesk wird beim ersten Start eingerichtet …")
        subprocess.check_call([sys.executable, "-m", "venv", str(VENV)])
    if not MARKER.exists() or MARKER.read_text(encoding="utf-8").strip() != fingerprint:
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
        python = ensure_installed()
        if args.install_only:
            print("ThreadDesk ist startbereit.")
            return 0
        print("ThreadDesk startet. Der Browser öffnet sich gleich …")
        return subprocess.call(
            [str(python), "-m", "threaddesk.ui.cli", "serve", "--open"], cwd=ROOT
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        print("ThreadDesk konnte nicht eingerichtet oder gestartet werden.", file=sys.stderr)
        print(f"Grund: {exc}", file=sys.stderr)
        print("Bitte kopiere diese Meldung vollständig in ein GitHub-Issue.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
