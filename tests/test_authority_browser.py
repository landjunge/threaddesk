"""Navigate from ThreadDesk to the actual read-only observer in Chromium."""

from __future__ import annotations

import hashlib
import json
import os
import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from playwright.sync_api import sync_playwright

from threaddesk.api.service import ThreadService
from threaddesk.storage.json_store import JsonStore
from threaddesk.ui.server import create_app


def _tree(root):
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        if p.is_file()
        else "directory"
        for p in root.rglob("*")
    }


@pytest.mark.parametrize("width", [1280, 390])
def test_user_opens_report_reads_evidence_and_returns(tmp_path, monkeypatch, width):
    monkeypatch.setenv("THREADDESK_HOME", str(tmp_path))
    monkeypatch.delenv("THREADDESK_STORAGE", raising=False)
    svc = ThreadService(JsonStore(tmp_path))
    thread = svc.create("Browser thread")
    svc.append_whiteboard(
        thread.id,
        actor="PRIVATE_BROWSER_ACTOR",
        actor_type="codex",
        entry_type="claimed",
        task_id="PRIVATE_BROWSER_TASK",
        content="PRIVATE_BROWSER_CONTENT",
    )
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    url = f"http://127.0.0.1:{listener.getsockname()[1]}"
    server = uvicorn.Server(uvicorn.Config(create_app(), log_level="error"))
    worker = threading.Thread(
        target=server.run, kwargs={"sockets": [listener]}, daemon=True
    )
    worker.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.05)
        assert server.started
        with sync_playwright() as play:
            browser = play.chromium.launch(
                executable_path=os.environ.get("THREADDESK_CHROMIUM") or None
            )
            page = browser.new_page(viewport={"width": width, "height": 900})
            page.goto(url + "/?lang=de", wait_until="networkidle")
            link = page.get_by_role("link", name="Beobachterbericht öffnen", exact=True)
            link.focus()
            before = _tree(tmp_path)
            requests = []
            page.on("request", lambda request: requests.append(request.url))
            link.press("Enter")
            page.wait_for_url(url + f"/threads/{thread.id}/authority")
            page.wait_for_load_state("networkidle")
            assert page.get_by_role(
                "heading", name="Agent Authority", exact=True
            ).is_visible()
            body = page.locator("body").inner_text()
            assert (
                "UNBEKANNT" in body
                and thread.id in body
                and "PRIVATE_BROWSER" not in body
            )
            assert requests == [url + f"/threads/{thread.id}/authority"]
            assert page.locator("script, img, link[rel=stylesheet]").count() == 0
            assert (
                page.evaluate(
                    "getComputedStyle(document.documentElement).backgroundColor"
                )
                == "rgb(243, 246, 250)"
            )
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            summary = page.locator("details > summary").first
            summary.focus()
            summary.press("Space")
            assert summary.evaluate("element => element.parentElement.open")
            assert "SHA256" in page.locator("details[open]").first.inner_text()
            assert _tree(tmp_path) == before
            evidence_dir = os.environ.get("AUTHORITY_QA_DIR")
            if evidence_dir:
                destination = Path(evidence_dir)
                destination.mkdir(parents=True, exist_ok=True)
                page.screenshot(
                    path=str(destination / f"authority-{width}.png"), full_page=True
                )
                (destination / f"authority-{width}.json").write_text(
                    json.dumps(
                        {
                            "viewport_width": width,
                            "report_requests": requests,
                            "source_unchanged": True,
                            "keyboard_disclosure": True,
                            "styled": True,
                            "no_outer_overflow": True,
                        },
                        indent=2,
                    )
                )
            page.go_back(wait_until="networkidle")
            assert page.get_by_role(
                "link", name="Beobachterbericht öffnen", exact=True
            ).is_visible()
            assert svc.current().id == thread.id
            browser.close()
    finally:
        server.should_exit = True
        worker.join(timeout=10)
        listener.close()
