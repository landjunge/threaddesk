"""Measured user-facing layout and keyboard regression checks, TD-DESIGN-02.

The five real pages retain their desktop composition, in both languages.
No screenshots substitute for behaviour assertions. All data is synthetic.
"""
import os

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect, sync_playwright

from test_desk_browser import Desk, _open_section
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
    for n in range(15):
        service.create(f"Weiterer Thread {n}")
    service.switch(thread.id)
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
      const visible = e => e.checkVisibility() && e.getClientRects().length && e.getBoundingClientRect().width > 0;
      const controls = [...document.querySelectorAll('.btn,.chip,.np-button,input:not([type=hidden]):not([type=checkbox]):not([type=radio]),select')].filter(visible);
      return {
        width: innerWidth, documentWidth: document.documentElement.scrollWidth,
        wrongHeight: controls.filter(e => Math.abs(e.getBoundingClientRect().height - height) > 1).map(e => [e.tagName,e.textContent,e.getBoundingClientRect().height]),
        outside: controls.filter(e => {const r=e.getBoundingClientRect(); return r.left < -1 || r.right > innerWidth + 1}).map(e => [e.tagName,e.textContent]),
        clippedLabels: controls.filter(e => e.matches('.btn,.chip,.np-button') && e.scrollWidth > e.clientWidth + 1).map(e => e.textContent),
        scrollbars: [...document.querySelectorAll('body *')].filter(e => visible(e) && ['auto','scroll'].includes(getComputedStyle(e).overflowY) && e.scrollHeight > e.clientHeight + 1 && getComputedStyle(e).scrollbarWidth !== 'none').map(e => e.className)
      };
    }""", control_height)
    assert result["documentWidth"] <= result["width"] + 1, result
    assert not result["wrongHeight"], result
    assert not result["outside"], result
    assert not result["clippedLabels"], result
    assert not result["scrollbars"], result


@pytest.mark.parametrize("width,height", [(1920,1080),(1440,900),(1280,800),(1180,760)])
@pytest.mark.parametrize("language", ["de", "en"])
def test_five_pages_use_consistent_desktop_controls(design_browser, width, height, language):
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
        for name in ["files", "snapshots", "prompt", "hausmeister", "graph_links", "packet", "notes"]:
            _open_section(page, name)
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


def test_desktop_edit_and_error_remain_usable(design_browser):
    browser, url = design_browser
    page = browser.new_page(viewport={"width":1180,"height":760})
    try:
        page.goto(url + "/lang/de", wait_until="networkidle")
        _open_section(page, "thread-edit")
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


def test_coarse_pointer_does_not_rearrange_desktop(design_browser):
    browser, url = design_browser
    page = browser.new_page(viewport={"width":1280,"height":800}, has_touch=True)
    try:
        for route in ["/", "/knowledge", "/data", "/migration", "/map"]:
            page.goto(url + route, wait_until="networkidle")
            assert_layout(page, control_height=40)
    finally:
        page.close()


@pytest.mark.parametrize("width", [1440, 1180])
def test_disclosed_tools_remain_usable(design_browser, width):
    browser, url = design_browser
    page = browser.new_page(viewport={"width": width, "height": 900})
    try:
        page.goto(url, wait_until="networkidle")
        expect(page.locator('.btn-primary:visible')).to_have_count(1)
        for name in ["thread-edit", "stand", "notes", "files", "snapshots", "prompt", "hausmeister", "graph_links", "packet", "room", "preferences"]:
            _open_section(page, name)
            assert_layout(page)
        page.reload(wait_until="networkidle")
        expect(page.locator('details[data-disclosure="snapshots"]')).to_have_attribute("open", "")
        page.locator('[data-whiteboard-content]').fill("Die neue Ordnung bleibt nach dem Speichern benutzbar.")
        page.locator('[data-whiteboard-submit]').click()
        expect(page.locator('[role="status"]')).to_have_text("Beitrag angehängt")
        expect(page.locator('details[data-disclosure="snapshots"]')).to_have_attribute("open", "")
        page.locator('details[data-disclosure="snapshots"] > summary').click()
        page.locator('h1').click()
        page.keyboard.press("s")
        expect(page.locator('[data-snapshot-label]')).to_be_focused()
    finally:
        page.close()


@pytest.mark.parametrize("width", [1440, 1280, 1180])
def test_same_portable_components_for_five_products(design_browser, width):
    browser, url = design_browser
    page = browser.new_page(viewport={"width": width, "height": 1000})
    foreign_requests = []
    page.on("request", lambda request: foreign_requests.append(request.url) if not request.url.startswith(url) else None)
    try:
        page.goto(url + "/static/design-reference.html", wait_until="networkidle")
        for key, title in [("netzwerkpunkt", "NetzwerkPunkt"), ("gnom", "Gnom-Hub-V1"), ("threaddesk", "ThreadDesk"), ("tollgate", "TollGate"), ("4allpass", "4AllPass")]:
            page.locator(f'[data-product="{key}"]').click()
            expect(page.locator('[data-name]')).to_have_text(title)
            expect(page.locator('[data-product][aria-pressed="true"]')).to_have_count(1)
            assert_layout(page)
        page.locator('[data-action]').click()
        expect(page.locator('#feedback')).to_contain_text("Es wurde nichts ausgeführt")
        assert not foreign_requests
    finally:
        page.close()


def test_smaller_viewport_keeps_desktop_order_and_access(design_browser):
    browser, url = design_browser
    page = browser.new_page(viewport={"width":1024,"height":700})
    try:
        page.goto(url, wait_until="networkidle")
        sizes = page.evaluate("""() => {
          const sidebar=document.querySelector('.sidebar').getBoundingClientRect();
          const main=document.querySelector('.main').getBoundingClientRect();
          const side=document.querySelector('.desk-side').getBoundingClientRect();
          const notes=document.querySelector('.desk-notes').getBoundingClientRect();
          return {width:document.querySelector('.shell').clientWidth,
            height:document.querySelector('.shell').clientHeight,
            columns:sidebar.right<=main.left && notes.right<=side.left,
            scrollable:getComputedStyle(document.documentElement).overflowX};
        }""")
        assert sizes["width"] >= 1180 and sizes["height"] >= 760, sizes
        assert sizes["columns"] and sizes["scrollable"] == "auto", sizes
        _open_section(page, "packet")
        page.locator('details[data-disclosure="packet"] .btn').last.focus()
        assert page.locator('details[data-disclosure="packet"] .btn').last.evaluate(
            "e => { const r=e.getBoundingClientRect(); return r.left>=0 && r.right<=innerWidth && r.top>=0 && r.bottom<=innerHeight; }")
    finally:
        page.close()
