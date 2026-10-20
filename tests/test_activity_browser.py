"""A real activity POST must finish without preventing normal page navigation."""

from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.parse import urlsplit

from test_desk_browser import CHROME, Desk
from playwright.sync_api import sync_playwright


def test_activity_post_finishes_during_networkidle_navigation(tmp_path: Path) -> None:
    home = tmp_path / "activity-desk"
    home.mkdir()
    desk = Desk(home)
    try:
        url = desk.start()
        assert urlsplit(url).port not in {8765, 8766, 8767}
        target = url + "/hausmeister/activity"
        with sync_playwright() as play:
            browser = play.chromium.launch(executable_path=CHROME, headless=True)
            try:
                page = browser.new_page()
                activity = {}

                def is_activity(request):
                    return request.url == target and request.method == "POST"

                def requested(request):
                    if is_activity(request):
                        activity[request] = {"status": None, "finished": False, "failed": None}

                def responded(response):
                    if is_activity(response.request):
                        activity[response.request]["status"] = response.status

                def finished(request):
                    if is_activity(request):
                        activity[request]["finished"] = True

                def failed(request):
                    if is_activity(request):
                        activity[request]["failed"] = request.failure

                # Observe the normal browser lifecycle, without consuming response bodies
                # or replacing fetch/CSRF. A response event alone is not completion.
                page.on("request", requested)
                page.on("response", responded)
                page.on("requestfinished", finished)
                page.on("requestfailed", failed)
                page.add_init_script("""
                    document.addEventListener('DOMContentLoaded', () => {
                        sendActivity('pointer');
                    }, {once: true});
                """)
                began = time.time()
                try:
                    response = page.goto(url + "/", wait_until="networkidle", timeout=30_000)
                except Exception as exc:
                    raise AssertionError(
                        f"Normal networkidle navigation failed; activity lifecycle: {list(activity.values())}"
                    ) from exc
                assert response.status == 200
                assert activity, "No real activity request was observed during navigation"
                observed = list(activity.values())
                assert all(item["finished"] and not item["failed"] for item in observed), observed
                assert all(item["status"] == 200 for item in observed), observed
                stored = json.loads((home / "hausmeister-activity.json").read_text(encoding="utf-8"))
                assert stored["kind"] == "pointer"
                assert began <= stored["seen"] <= time.time()
            finally:
                browser.close()
    finally:
        desk.stop()
