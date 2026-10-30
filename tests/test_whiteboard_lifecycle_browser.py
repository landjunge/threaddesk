"""Actual UI and live graph follow external lifecycle commits on one saved board."""
from __future__ import annotations

import os
import re
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from test_desk_browser import Desk
from threaddesk.api.service import ThreadService
from threaddesk.services.commands import CommandApplication
from threaddesk.storage.json_store import JsonStore
from test_whiteboard_lifecycle import invoke, current


def test_whiteboard_ui_corrections_state_and_live_graph(tmp_path):
    home = tmp_path / "workspace"
    app = CommandApplication(ThreadService(JsonStore(home)))
    thread = invoke(app, "whiteboard.create", {"title": "Whiteboard für Abnahme"},
                    operation="create-browser", revision=0)["result"]["thread"]
    identity = thread["id"]
    node_id = "wb-" + identity
    original = app.service.append_whiteboard(identity, actor="Mensch", actor_type="human",
        entry_type="note", content="Unveränderliches Original")["entry"]
    desk = Desk(home)
    url = desk.start()
    try:
        with sync_playwright() as play:
            browser = play.chromium.launch(executable_path=os.environ.get("THREADDESK_CHROMIUM") or None)
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            editor = context.new_page()
            graph = context.new_page()
            errors = []
            editor.on("pageerror", lambda error: errors.append(str(error)))
            graph.on("pageerror", lambda error: errors.append(str(error)))
            graph.goto(url + "/map", wait_until="networkidle")
            board_node = graph.locator(f'.map-node[data-node-id="{node_id}"]')
            expect(board_node).to_have_count(1)
            expect(board_node).to_have_attribute("data-kind", "whiteboard")
            board_node.click()
            expect(graph.locator("[data-map-whiteboard-state]")).to_have_attribute("data-map-whiteboard-state", "open")
            editor.goto(url + "/?thread=" + identity, wait_until="networkidle")
            entry = editor.locator(f'[data-entry-id="{original["id"]}"]')
            entry.locator("[data-whiteboard-edit] summary").click()
            entry.locator("textarea[name=content]").fill("Bearbeitet über ThreadDesk")
            entry.locator("[data-whiteboard-edit] button[type=submit]").click()
            expect(editor.locator(f'[data-entry-id="{original["id"]}"] .whiteboard-body')).to_have_text("Bearbeitet über ThreadDesk")
            expect(editor.locator("[data-whiteboard-correction]")).to_contain_text("Unveränderliches Original")
            assert app.store.list_whiteboard(identity)[0].content == "Unveränderliches Original"
            editor.locator('[data-whiteboard-controls] form button[type=submit]').click()
            expect(editor.locator('[data-whiteboard-state]')).to_have_attribute("data-whiteboard-state", "closed")
            expect(editor.locator("[data-whiteboard-content]")).to_have_count(0)
            expect(board_node).to_have_attribute("data-status", "paused", timeout=15000)
            board_node.click()
            expect(graph.locator("[data-map-whiteboard-state]")).to_have_attribute("data-map-whiteboard-state", "closed")
            editor.locator('[data-whiteboard-controls] form button[type=submit]').click()
            expect(editor.locator("[data-whiteboard-content]")).to_be_visible()
            # A stale edit is rejected in-place; the exact draft survives.
            entry = editor.locator(f'[data-entry-id="{original["id"]}"]')
            entry.locator("[data-whiteboard-edit] summary").click()
            entry.locator("textarea[name=content]").fill("Entwurf bleibt bei Konflikt")
            invoke(app, "whiteboard.rename", {"id": identity, "title": "Neuer Whiteboardname"},
                   operation="rename-external", revision=current(app, identity))
            entry.locator("[data-whiteboard-edit] button[type=submit]").click()
            expect(entry.locator("textarea[name=content]")).to_have_value("Entwurf bleibt bei Konflikt")
            expect(graph.locator(f'.map-node[data-node-id="{node_id}"]')).to_have_attribute("aria-label", re.compile(r"^Neuer Whiteboardname, whiteboard, active"), timeout=15000)
            invoke(app, "whiteboard.archive", {"id": identity}, operation="archive-external", revision=current(app, identity))
            expect(board_node).to_have_attribute("data-status", "archived", timeout=15000)
            invoke(app, "whiteboard.unarchive", {"id": identity}, operation="unarchive-external", revision=current(app, identity))
            moved = invoke(app, "whiteboard.delete", {"id": identity, "confirm_thread_move": True},
                operation="delete-external", revision=current(app, identity))["result"]["entry"]
            expect(board_node).to_have_count(0, timeout=15000)
            invoke(app, "whiteboard.restore", {"trash_id": moved["trash_id"], "generation": moved["generation"]},
                operation="restore-external", revision=moved["revision"])
            expect(board_node).to_have_count(1, timeout=15000)
            expect(board_node).to_have_attribute("data-status", "active")
            editor.goto(url + "/whiteboards", wait_until="networkidle")
            expect(editor.locator(f'[data-whiteboard-id="{identity}"]')).to_contain_text("Neuer Whiteboardname")
            shots = Path(os.environ.get("THREADDESK_WHITEBOARD_SHOTS", "/tmp/threaddesk-dynamic-mcp-20261030/screenshots"))
            shots.mkdir(parents=True, exist_ok=True)
            board_node.click()
            graph.screenshot(path=str(shots / "whiteboard-live-graph.png"))
            editor.screenshot(path=str(shots / "whiteboards-list.png"))
            assert errors == []
            browser.close()
    finally:
        desk.stop()
