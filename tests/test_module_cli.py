import argparse
import json

from threaddesk.api.service import ThreadService
from threaddesk.storage.json_store import JsonStore
from threaddesk.ui import cli


def test_cli_installs_enables_and_creates_workshop(monkeypatch, tmp_path, capsys):
    service = ThreadService(JsonStore(tmp_path))
    monkeypatch.setattr(cli, "_svc", lambda: service)
    cli.cmd_module(argparse.Namespace(module_cmd="install", module_id="workshop"))
    cli.cmd_module(argparse.Namespace(
        module_cmd="enable",
        module_id="workshop",
        approve=["knowledge:link", "contact:link"],
    ))
    cli.cmd_workshop(argparse.Namespace(
        workshop_cmd="create",
        event_id="autumn-lab",
        title="Autumn Lab",
        audience="Teenagers",
        course_level="Advanced",
        schedule="2026-10-12 09:00",
        location="Studio 2",
        material=["Clay"],
        participant=["person-1"],
        task=["task-1"],
        step=["Prepare", "Run", "Review"],
    ))
    stored = json.loads((tmp_path / "module-workshop-data.json").read_text(encoding="utf-8"))
    assert stored["records"]["autumn-lab"]["workflow_steps"] == ["Prepare", "Run", "Review"]
    assert "autumn-lab" in capsys.readouterr().out


def test_cli_disable_and_uninstall_preserve_workshop_data(monkeypatch, tmp_path):
    service = ThreadService(JsonStore(tmp_path))
    monkeypatch.setattr(cli, "_svc", lambda: service)
    (tmp_path / "module-workshop-data.json").write_text('{"schema_version":1,"records":{"event":{}}}', encoding="utf-8")
    cli.cmd_module(argparse.Namespace(module_cmd="install", module_id="workshop"))
    cli.cmd_module(argparse.Namespace(module_cmd="disable", module_id="workshop"))
    cli.cmd_module(argparse.Namespace(module_cmd="uninstall", module_id="workshop"))
    assert (tmp_path / "module-workshop-data.json").exists()
