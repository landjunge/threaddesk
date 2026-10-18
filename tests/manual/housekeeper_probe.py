"""Explicit optional real-model probe from PR66, not deterministic CI acceptance.
Run only with an operator-approved existing local model and the opt-in variable.
"""

import os
import sys
from pathlib import Path
import pytest
from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_desk_browser import (
    Desk,
    _chrome_pids,
    _launch,
    _raise_chrome,
    _shot,
    _create,
    _open_section,
)


def test_user_runs_the_housekeeper_on_an_installed_model(tmp_path: Path) -> None:
    """TD-HAUS-01. Echter lokaler Auftrag nur mit THREADDESK_HAUSMEISTER_LIVE=1.

    Die normale Suite setzt die Variable nicht und ruft Ollama dafür nicht auf.
    Ein Lauf beweist keine Antwortqualität.
    """
    if os.environ.get("THREADDESK_HAUSMEISTER_LIVE") != "1":
        pytest.skip("Live-Modelltest benötigt THREADDESK_HAUSMEISTER_LIVE=1")
    home = tmp_path / "desk"
    home.mkdir()
    desk = Desk(home)
    page_errors: list[str] = []
    try:
        url = desk.start()
        with sync_playwright() as play:
            before = _chrome_pids()
            browser = _launch(play)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.bring_to_front()
            page.on("pageerror", lambda exc: page_errors.append(str(exc)))
            page.goto(url + "/lang/de", wait_until="networkidle")
            page.wait_for_function("() => window.Alpine !== undefined")
            _raise_chrome(before)
            _create(page, "Hausmeister live")
            _open_section(page, "hausmeister")
            _open_section(page, "hausmeister")
            section = page.locator("[data-hausmeister]")
            section.scroll_into_view_if_needed()
            section.get_by_role("button", name="Einschalten", exact=True).click()
            names = page.locator("[data-hausmeister-model] option").evaluate_all(
                "els => els.map((el) => el.value).filter(Boolean)"
            )
            small = next((name for name in names if str(name).endswith(":1b")), "")
            assert small, names
            page.locator("[data-hausmeister-model]").select_option(small)
            section.get_by_role("button", name="Modell übernehmen", exact=True).click()
            expect(page.get_by_role("status")).to_have_text("Modell übernehmen")
            page.locator("[data-hausmeister-order]").fill(
                "Fasse den Thread in einem Satz zusammen"
            )
            page.locator("[data-hausmeister-run]").click()
            expect(page.get_by_role("status")).to_have_text(
                "Auftrag angehängt", timeout=120000
            )
            expect(page.locator("[data-hausmeister-entry]").first).to_be_visible()
            _raise_chrome(before, "fenster-hausmeister-lauf.png")
            _shot(page, "14-hausmeister-lauf.png")
            browser.close()
    finally:
        desk.stop()
    assert page_errors == []
