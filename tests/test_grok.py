from pathlib import Path

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.core.errors import InvalidState
from threaddesk.services.mcp import McpBridge
from threaddesk.storage.json_store import JsonStore


@pytest.fixture
def svc(tmp_path: Path) -> ThreadService:
    return ThreadService(store=JsonStore(tmp_path))


def test_grok_writes_packet_and_does_not_run(svc: ThreadService, tmp_path: Path) -> None:
    svc.create("Switcher", "Kontext halten")
    svc.set_note("nächster Schritt: Bridge")
    packet = svc.grok()
    assert packet["kind"] == "threaddesk.grok"
    assert packet["mode"] == "brainstorm"
    assert packet["ran"] is False
    assert Path(packet["path"]).is_file()
    assert Path(packet["prompt_path"]).is_file()
    assert "grok --prompt-file" in packet["command"]
    assert "search_replace" in packet["command"]
    assert "run_terminal_cmd" in packet["command"]
    assert "--yolo" not in packet["command"]
    assert "Brainstorm" in packet["prompt"]
    assert "Switcher" in packet["prompt"]
    assert "Bridge" in packet["prompt"]


def test_grok_execute_still_does_not_run(svc: ThreadService) -> None:
    svc.create("Execute Me")
    packet = svc.grok(mode="execute")
    assert packet["mode"] == "execute"
    assert packet["ran"] is False
    assert "--yolo" not in packet["command"]
    assert "search_replace" not in packet["command"]
    assert "Execute" in packet["prompt"]
    with pytest.raises(InvalidState):
        svc.grok(mode="launch")


def test_mcp_export_grok(svc: ThreadService) -> None:
    svc.create("Via MCP")
    got = McpBridge(svc).call("export_grok", {"mode": "brainstorm"})
    assert got["ok"]
    assert got["result"]["ran"] is False
    assert Path(got["result"]["path"]).is_file()
