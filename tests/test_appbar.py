"""Portable renderer sources and real browser fixture; no app/peer admission."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src/threaddesk/ui/static"


def test_pure_state_contract():
    subprocess.run(["node", "--test", str(ROOT / "tests/appbar_state.test.mjs")], cwd=ROOT, check=True)


def test_approved_asset_hashes_and_no_bridge_substitute():
    manifest = json.loads((STATIC / "networkpunkt-appbar-assets.json").read_text())
    assert manifest["blocked"]["kirabridge"] == "approved-icon-missing"
    assert [x["appId"] for x in manifest["files"]] == ["threaddesk", "4allpass"]
    for line in (STATIC / "networkpunkt-appbar-SHA256SUMS").read_text().splitlines():
        digest, name = line.split("  ", 1)
        assert hashlib.sha256((STATIC / name).read_bytes()).hexdigest() == digest
    assert not list(STATIC.glob("np-appbar-kirabridge*"))


@pytest.fixture()
def appbar():
    with sync_playwright() as play:
        installed = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        executable = os.environ.get("THREADDESK_CHROMIUM") or (str(installed) if installed.exists() else None)
        browser = play.chromium.launch(executable_path=executable)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def route(request):
            path = request.request.url.split(".invalid", 1)[-1]
            if path == "/":
                request.fulfill(path=str(ROOT / "tests/fixtures/appbar.html"), content_type="text/html")
            elif path.startswith("/static/") and "/" not in path[len("/static/"):]:
                file = STATIC / path[len("/static/"):]
                assert file.name.startswith(("networkpunkt", "np-appbar")) and file.is_file()
                content_type = "text/javascript" if file.suffix == ".js" else "text/css" if file.suffix == ".css" else "image/png"
                request.fulfill(path=str(file), content_type=content_type)
            else:
                request.abort()

        page.route("https://appbar-fixture.invalid/**", route)
        page.route("**/*", lambda route: route.fallback() if route.request.url.startswith("https://appbar-fixture.invalid/") else route.abort())
        page.goto("https://appbar-fixture.invalid/")
        page.wait_for_function("window.ready === true")
        try:
            yield page
            assert not errors
        finally:
            page.close()
            browser.close()


def ring(page, app="4allpass"):
    return page.locator(f'[data-app-id="{app}"] .np-appbar-ring')


def test_real_dom_states_scope_staleness_and_reconnect(appbar):
    page = appbar
    assert "Status unbekannt" in page.locator('[data-app-id="4allpass"]').get_attribute("aria-label")
    page.evaluate('check("4allpass", {vault:{userRef:"fixture-user",vaultRef:"fixture-vault",allowed:true,state:"unlocked",ttlMs:1000}})')
    assert ring(page).get_attribute("data-pulse") == "true"
    page.evaluate("advance(1000)")
    assert ring(page).get_attribute("data-connected") == "true"
    assert ring(page).get_attribute("data-pulse") == "false"
    assert "Tresorstatus unbekannt" in page.locator('[data-app-id="4allpass"]').get_attribute("aria-label")
    page.evaluate('bar.fail("4allpass", bar.begin("4allpass"), "error")')
    assert ring(page).get_attribute("data-connected") == "false"
    page.evaluate('check("4allpass")')
    assert ring(page).get_attribute("data-connected") == "true"
    page.evaluate('document.dispatchEvent(new Event("visibilitychange"))')
    assert ring(page).get_attribute("data-connected") == "false"


@pytest.mark.parametrize("locale", ["de", "en"])
def test_keyboard_tooltip_open_dedup_and_no_false_connection(appbar, locale):
    page = appbar
    page.evaluate("locale => bar.setLocale(locale)", locale)
    button = page.locator('[data-app-id="4allpass"]')
    button.focus()
    assert page.locator("#np-appbar-tip-1-4allpass").is_visible()
    page.keyboard.press("Escape")
    assert not page.locator("#np-appbar-tip-1-4allpass").is_visible()
    page.keyboard.press("Enter")
    page.keyboard.press("Space")
    button.dispatch_event("click")
    assert page.evaluate("openCalls.length") == 1
    assert button.get_attribute("aria-disabled") == "true"
    page.evaluate('resolvers[0]("opened")')
    page.wait_for_function('document.querySelector("[data-app-id=\\"4allpass\\"]").getAttribute("aria-disabled") === "false"')
    assert ring(page).get_attribute("data-connected") == "false"
    label = button.get_attribute("aria-label")
    assert ("App geöffnet, Verbindung fehlt" if locale == "de" else "App opened, connection missing") in label
    page.keyboard.press("Tab")
    assert page.locator("#after").evaluate("e => e === document.activeElement")


def test_unknown_open_result_late_response_and_remount_are_safe(appbar):
    page = appbar
    page.locator('[data-app-id="threaddesk"]').click()
    page.evaluate("advance(2000)")
    page.evaluate('resolvers[0]("opened")')
    page.locator('[data-app-id="threaddesk"]').dispatch_event("click")
    assert page.evaluate("openCalls.length") == 1
    assert "Öffnung unklar" in page.locator('[data-app-id="threaddesk"]').get_attribute("aria-label")
    page.evaluate("mountAgain(); mountAgain()")
    assert page.locator(".np-appbar").count() == 1
    assert page.evaluate("activeIntervals.size") == 1
    page.evaluate("bar.destroy(); bar.destroy()")
    assert page.locator(".np-appbar").count() == 0
    assert page.evaluate("activeIntervals.size") == 0
    assert page.evaluate('bar.begin("4allpass")') is None
    assert page.evaluate('bar.receive("4allpass", {}, observation("4allpass"))') is False


def test_actual_periodic_expiry_and_failed_open_message(appbar):
    page = appbar
    page.evaluate('check("4allpass", {ttlMs:500})')
    page.evaluate("time+=500;wall+=500")
    page.wait_for_function('document.querySelector("[data-app-id=\\"4allpass\\"] .np-appbar-ring").dataset.connected === "false"')
    page.locator('[data-app-id="4allpass"]').click()
    page.evaluate('resolvers[0]("failed")')
    page.wait_for_function('document.querySelector("[data-app-id=\\"4allpass\\"]").dataset.error === "true"')
    assert "Öffnen fehlgeschlagen" in page.locator('[data-app-id="4allpass"]').get_attribute("aria-label")
    assert ring(page).get_attribute("data-connected") == "false"


def test_fast_success_double_click_still_opens_once(appbar):
    page = appbar
    page.evaluate('options.onOpen=async args=>{openCalls.push({appId:args.appId,actionId:args.actionId});return {actionId:args.actionId,outcome:"opened"};};mountAgain()')
    page.locator('[data-app-id="4allpass"]').dblclick()
    assert page.evaluate("openCalls.length") == 1
    assert ring(page).get_attribute("data-connected") == "false"


def test_missing_approved_tool_color_keeps_default_catalog_neutral(appbar):
    page = appbar
    page.evaluate('options.colors={};mountAgain();check("4allpass", {vault:{userRef:"fixture-user",vaultRef:"fixture-vault",allowed:true,state:"unlocked",ttlMs:1000}})')
    assert ring(page).get_attribute("data-connected") == "false"
    assert ring(page).get_attribute("data-pulse") == "false"
    assert "Statusanzeige nicht eingerichtet" in page.locator('[data-app-id="4allpass"]').get_attribute("aria-label")


@pytest.mark.parametrize("width", [1440, 320])
def test_fixed_icon_geometry_and_only_ring_motion(appbar, width):
    page = appbar
    page.set_viewport_size({"width": width, "height": 760})
    before = page.locator(".np-appbar-button").evaluate_all("es => es.map(e => {const r=e.getBoundingClientRect();return [r.x,r.y,r.width,r.height]})")
    page.evaluate('check("4allpass", {vault:{userRef:"fixture-user",vaultRef:"fixture-vault",allowed:true,state:"unlocked",ttlMs:15000}})')
    after = page.locator(".np-appbar-button").evaluate_all("es => es.map(e => {const r=e.getBoundingClientRect();return [r.x,r.y,r.width,r.height]})")
    assert before == after
    assert all(r[2:] == [40, 40] and r[0] >= 0 and r[0] + r[2] <= width for r in after)
    assert after[1][0] - after[0][0] == 44
    assert ring(page).evaluate('e => getComputedStyle(e,"::before").animationDuration') == "12s"
    assert ring(page).locator("img").evaluate("e => getComputedStyle(e).opacity") == "1"
    page.emulate_media(reduced_motion="reduce")
    assert ring(page).evaluate('e => getComputedStyle(e,"::before").animationName') == "none"
    assert "Tresor entsperrt" in page.locator('[data-app-id="4allpass"]').get_attribute("aria-label")
