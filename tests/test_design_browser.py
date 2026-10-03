"""Measured user-facing layout and keyboard regression checks, TD-DESIGN-01.

The five real pages are checked at desktop and reflow widths, in both languages.
No screenshots substitute for behaviour assertions. All data is synthetic.
"""
import os

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect, sync_playwright

from test_desk_browser import Desk
from threaddesk.api.service import ThreadService
from threaddesk.storage.json_store import JsonStore


@pytest.fixture(scope="module")
def design_browser(tmp_path_factory):
    home = tmp_path_factory.mktemp("design-workspace")
    service = ThreadService(store=JsonStore(home))
    thread = service.create("Oberfläche mit langem Titel – " + "Arbeitsplatz " * 8)
    service.set_note("Lange Notizen bleiben lesbar.\n" * 40)
    service.create_node("project", "Projekt mit einer ausführlichen Beschreibung",
                        status="active", details="Ein langer Text. " * 30)
    service.create_node("task", "Darstellung bei schmalen Fenstern prüfen",
                        status="in_progress")
    for n in range(12):
        service.append_whiteboard(thread.id, actor="Testperson", actor_type="human",
                                  entry_type="note", content=f"Beitrag {n}: " + "Text " * 50)
    desk = Desk(home)
    url = desk.start()
    try:
        with sync_playwright() as play:
            # Missing browser is a failed verification, not a green skipped check.
            browser = play.chromium.launch(executable_path=os.environ.get("THREADDESK_CHROMIUM"))
            yield browser, url
            browser.close()
    finally:
        desk.stop()


def assert_layout(page, control_height=40):
    result = page.evaluate("""height => {
      const visible = e => e.getClientRects().length && e.getBoundingClientRect().width > 0;
      const controls = [...document.querySelectorAll('.btn,.chip,input:not([type=hidden]):not([type=checkbox]):not([type=radio]),select')].filter(visible);
      return {
        width: innerWidth, documentWidth: document.documentElement.scrollWidth,
        wrongHeight: controls.filter(e => Math.abs(e.getBoundingClientRect().height - height) > 1).map(e => [e.tagName,e.textContent,e.getBoundingClientRect().height]),
        outside: controls.filter(e => {const r=e.getBoundingClientRect(); return r.left < -1 || r.right > innerWidth + 1}).map(e => [e.tagName,e.textContent]),
        clippedLabels: controls.filter(e => e.matches('.btn,.chip') && e.scrollWidth > e.clientWidth + 1).map(e => e.textContent),
        scrollbars: [...document.querySelectorAll('body *')].filter(e => visible(e) && ['auto','scroll'].includes(getComputedStyle(e).overflowY) && e.scrollHeight > e.clientHeight + 1 && getComputedStyle(e).scrollbarWidth !== 'none').map(e => e.className)
      };
    }""", control_height)
    assert result["documentWidth"] <= result["width"] + 1, result
    assert not result["wrongHeight"], result
    assert not result["outside"], result
    assert not result["clippedLabels"], result
    assert not result["scrollbars"], result


@pytest.mark.parametrize("width,height", [(1440,1000),(1280,800),(1024,768),(768,900),(375,812),(320,800)])
@pytest.mark.parametrize("language", ["de", "en"])
def test_five_pages_reflow_with_consistent_controls(design_browser, width, height, language):
    browser, url = design_browser
    page = browser.new_page(viewport={"width":width,"height":height})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        page.goto(url + "/lang/" + language)
        for route in ["/", "/knowledge", "/data", "/migration", "/map"]:
            page.goto(url + route, wait_until="networkidle")
            expect(page.locator("h1").first).to_be_visible()
            assert_layout(page)
        assert not errors
    finally:
        page.close()


def test_hidden_scrollbars_keep_keyboard_access_and_dialog_focus(design_browser):
    browser, url = design_browser
    page = browser.new_page(viewport={"width":1440,"height":800})
    try:
        page.goto(url + "/", wait_until="networkidle")
        for selector in [".sidebar", ".desk-side", ".desk-notes", ".whiteboard-log"]:
            region = page.locator(selector)
            assert region.evaluate("e => e.scrollHeight > e.clientHeight"), selector
            region.focus()
            page.keyboard.press("End")
            page.wait_for_function("s => document.querySelector(s).scrollTop > 0", arg=selector)
        opener = page.locator("[data-help-open]")
        opener.click()
        close = page.locator("[data-help-close]")
        expect(close).to_be_focused()
        page.keyboard.press("Tab")
        expect(close).to_be_focused()
        page.keyboard.press("Shift+Tab")
        expect(close).to_be_focused()
        page.keyboard.press("Escape")
        expect(page.locator("#help")).to_be_hidden()
        expect(opener).to_be_focused()
    finally:
        page.close()


def test_small_window_edit_and_error_remain_usable(design_browser):
    browser, url = design_browser
    page = browser.new_page(viewport={"width":320,"height":800})
    try:
        page.goto(url + "/lang/de", wait_until="networkidle")
        page.locator('.desk-description input[name="text"]').fill("Beschreibung " * 25)
        page.locator('.desk-description button').click()
        expect(page.locator('[role="status"]')).to_contain_text("Beschreibung gespeichert")
        page.reload(wait_until="networkidle")
        expect(page.locator('.desk-description input[name="text"]')).to_have_value(("Beschreibung " * 25).strip())
        assert_layout(page)
        page.goto(url + "/data", wait_until="networkidle")
        page.locator('#backup-file').set_input_files({"name":"invalid.zip","mimeType":"application/zip","buffer":b"invalid"})
        page.locator('[name="confirm"]').check()
        page.locator('form[action="/data/restore"] button').click()
        expect(page.locator('[role="alert"]')).to_be_visible()
        assert_layout(page)
    finally:
        page.close()


def test_touch_controls_grow_together(design_browser):
    browser, url = design_browser
    page = browser.new_page(viewport={"width":390,"height":844}, is_mobile=True, has_touch=True)
    try:
        for route in ["/", "/knowledge", "/data", "/migration", "/map"]:
            page.goto(url + route, wait_until="networkidle")
            assert_layout(page, control_height=44)
    finally:
        page.close()
