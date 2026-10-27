"""A rejected stale editor keeps its actual DOM draft and reports the conflict."""
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

from threaddesk.api.service import ThreadService
from threaddesk.storage.json_store import JsonStore
from test_desk_browser import Desk, _launch, _open_section


@pytest.mark.parametrize("language", ["de", "en"])
def test_two_editors_keep_stale_draft_without_overwriting(tmp_path: Path, language):
    svc = ThreadService(JsonStore(tmp_path))
    thread = svc.create("Independent editors")
    desk = Desk(tmp_path)
    url = desk.start()
    try:
        with sync_playwright() as play:
            browser = _launch(play)
            first = browser.new_page(viewport={"width": 1440, "height": 900})
            second = browser.new_page(viewport={"width": 1440, "height": 900})
            for page in (first, second):
                page.goto(url + "/?lang=" + language, wait_until="networkidle")
                _open_section(page, "notes")
            first.locator('#notes textarea[name="text"]').fill("First writer is retained")
            second.locator('#notes textarea[name="text"]').fill("Second editor unsaved draft")
            with first.expect_response(lambda response: response.url.endswith("/note")) as saved:
                first.locator('#notes form[hx-post$="/note"] button[type="submit"]').click()
            assert saved.value.status == 200
            with second.expect_response(lambda response: response.url.endswith("/note")) as rejected:
                second.locator('#notes form[hx-post$="/note"] button[type="submit"]').click()
            assert rejected.value.status == 409
            expect(second.locator('#notes textarea[name="text"]')).to_have_value("Second editor unsaved draft")
            expect(second.locator('#request-state[data-state="rejected"]')).to_contain_text(
                "Entwurf bleibt erhalten" if language == "de" else "draft is retained")
            assert svc.get(thread.id).context.notes == "First writer is retained"
            second.reload(wait_until="networkidle")
            _open_section(second, "notes")
            expect(second.locator('#notes textarea[name="text"]')).to_have_value("First writer is retained")
            browser.close()
    finally:
        desk.stop()
