from __future__ import annotations

import importlib.util
from pathlib import Path


def load_start():
    path = Path(__file__).parents[1] / "start.py"
    spec = importlib.util.spec_from_file_location("threaddesk_start", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_install_creates_venv_and_installs_ui_once(tmp_path, monkeypatch) -> None:
    start = load_start()
    monkeypatch.setattr(start, "ROOT", tmp_path)
    monkeypatch.setattr(start, "VENV", tmp_path / ".venv")
    monkeypatch.setattr(start, "MARKER", tmp_path / ".venv" / ".threaddesk-ready")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    python = start.venv_python()
    calls = []

    def fake_check_call(command, cwd=None):
        calls.append((command, cwd))
        if command[1:3] == ["-m", "venv"]:
            python.parent.mkdir(parents=True)
            python.touch()

    monkeypatch.setattr(start.subprocess, "check_call", fake_check_call)

    assert start.ensure_installed() == python
    assert calls[0][0][1:3] == ["-m", "venv"]
    assert calls[1][0][-2:] == ["-e", ".[ui]"]
    assert start.ensure_installed() == python
    assert len(calls) == 2


def test_main_starts_ui_through_venv_python(tmp_path, monkeypatch) -> None:
    start = load_start()
    python = tmp_path / "python"
    monkeypatch.setattr(start, "ensure_installed", lambda: python)
    installer_calls = []
    monkeypatch.setattr(start, "open_installer", lambda: installer_calls.append(True))
    calls = []
    monkeypatch.setattr(
        start.subprocess,
        "call",
        lambda command, cwd=None: calls.append((command, cwd)) or 0,
    )

    assert start.main([]) == 0
    assert installer_calls == [True]
    assert calls[0][0] == [
        str(python),
        "-m",
        "threaddesk.ui.cli",
        "serve",
        "--open",
    ]


def test_open_installer_opens_local_html(tmp_path, monkeypatch) -> None:
    start = load_start()
    monkeypatch.setattr(start, "ROOT", tmp_path)
    (tmp_path / "installer.html").write_text("<!doctype html>", encoding="utf-8")
    opened = []
    monkeypatch.setattr(start.webbrowser, "open", lambda url: opened.append(url))

    start.open_installer()

    assert opened == [(tmp_path / "installer.html").as_uri()]
