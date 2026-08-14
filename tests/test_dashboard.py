from pathlib import Path

from threaddesk.api.service import ThreadService
from threaddesk.services.mcp import McpBridge
from threaddesk.storage.json_store import JsonStore


def test_dashboard_writes_escaped_board(tmp_path: Path) -> None:
    svc = ThreadService(store=JsonStore(tmp_path))
    t = svc.create("<script>alert(1)</script>", "xss")
    svc.set_note("<img src=x onerror=alert(1)> notiz")
    svc.set_status("active")
    svc.create("Andere Idee")
    board = svc.dashboard()
    html = Path(board["html_path"]).read_text(encoding="utf-8")
    assert board["kind"] == "threaddesk.dashboard"
    assert Path(board["path"]).is_file()
    assert t.id in board["text"]
    assert "Andere Idee" in board["text"]
    assert board["counts"]["active"] == 1
    assert board["counts"]["idea"] == 1
    assert "<script>" not in html
    assert "<img" not in html
    assert "&lt;script&gt;" in html
    assert "&lt;img" in html
    assert "nur Ansicht" in html


def test_dashboard_hides_archive_and_mcp_is_read_only(tmp_path: Path) -> None:
    svc = ThreadService(store=JsonStore(tmp_path))
    a = svc.create("Weg")
    svc.archive(a.id)
    svc.create("Bleibt")
    hidden = svc.dashboard()
    assert hidden["counts"]["archived"] == 0
    shown = svc.dashboard(include_archived=True)
    assert shown["counts"]["archived"] == 1
    names = [t["name"] for t in McpBridge(svc).list_tools()]
    assert "dashboard" in names
    assert "delete" not in names
    got = McpBridge(svc).call("dashboard", {})
    assert got["ok"]
    assert got["result"]["kind"] == "threaddesk.dashboard"
    assert "text" not in got["result"]
    for card in got["result"]["columns"]["idea"]:
        assert "notes" not in card
        assert "notes_preview" in card
