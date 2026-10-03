"""Browserabnahme der Schreibtisch-Kernabläufe.

Ablaufkennungen: TD-START-01, TD-THREAD-01, TD-NOTE-01, TD-SNAP-01.
Der Nutzer arbeitet nur mit den angebotenen Schaltflächen. Der Server ist ein
eigener Prozess. Neuladen und ein zweiter Start lesen denselben synthetischen
Arbeitsbereich. Ein Zwischenstand setzt Notizen zurück und lässt den Verlauf
stehen.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")

from playwright.sync_api import expect, sync_playwright  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CHROME = os.environ.get("THREADDESK_CHROMIUM") or None
HEADED = os.environ.get("THREADDESK_BROWSER_HEADED") == "1"
SHOTS = os.environ.get("THREADDESK_SHOTS")

TITLE = "Prüfthread ÄÖÜ"
DESCRIPTION = "Sichtbarer Zweck für den ersten Thread"
NOTE = "Notiz übersteht Neuladen und Neustart."
LATER = "Dieser Text darf nach dem Laden verschwinden."
BOARD = "Dieser Verlauf bleibt beim Zwischenstand."
LABEL = "vor der Änderung"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_until_up(url: str) -> None:
    import urllib.request

    deadline = time.monotonic() + 20
    last = ""
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url + "/", timeout=1) as response:
                if response.status == 200:
                    return
        except Exception as exc:  # noqa: BLE001 - Start kann kurz fehlen
            last = str(exc)
            time.sleep(0.1)
    raise AssertionError(f"Server antwortet nicht auf {url}: {last}")


class Desk:
    """Ein ThreadDesk-Prozess auf einem synthetischen Arbeitsbereich."""

    def __init__(self, home: Path) -> None:
        self.home = home
        self.url = ""
        self.proc: subprocess.Popen[bytes] | None = None

    def start(self) -> str:
        port = _free_port()
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "src")
        env["THREADDESK_HOME"] = str(self.home)
        env.pop("THREADDESK_STORAGE", None)
        self.proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "threaddesk.ui.cli",
                "serve",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=ROOT,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        self.url = f"http://127.0.0.1:{port}"
        try:
            _wait_until_up(self.url)
        except Exception:
            self.stop()
            raise
        return self.url

    def stop(self) -> None:
        proc = self.proc
        self.proc = None
        if proc is None or proc.poll() is not None:
            return
        os.killpg(proc.pid, 15)
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, 9)
            proc.wait(timeout=5)


def _chrome_pids() -> set[int]:
    out = subprocess.check_output(["ps", "-ax", "-o", "pid=,command="], text=True)
    found: set[int] = set()
    for line in out.splitlines():
        if "Google Chrome.app/Contents/MacOS/Google Chrome" in line and "Helper" not in line:
            found.add(int(line.split(None, 1)[0]))
    return found


def _raise_chrome(before: set[int], shot: str | None = None) -> int | None:
    """Holt das Testfenster nach vorn. Ohne Helfer bleibt der Lauf kopflos gültig."""
    helper = Path("/tmp/td-raise")
    if not HEADED or not helper.exists():
        return None
    new = sorted(_chrome_pids() - before)
    if not new:
        return None
    pid = new[-1]
    subprocess.run([str(helper), str(pid), "activate"], check=False)
    front = subprocess.run([str(helper), str(pid), "front"], capture_output=True, text=True)
    if front.returncode != 0:
        raise AssertionError(f"Chrome ist nicht das vordere Fenster: {front.stdout.strip()}")
    if SHOTS and shot:
        listed = subprocess.run(
            [str(helper), str(pid), "windows"], capture_output=True, text=True
        )
        window_id = listed.stdout.split("\t", 1)[0].strip()
        if window_id.isdigit():
            subprocess.run(
                ["screencapture", "-l", window_id, "-o", str(Path(SHOTS) / shot)],
                check=False,
            )
    return pid


def _shot(page, name: str) -> None:
    if not SHOTS:
        return
    folder = Path(SHOTS)
    folder.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(folder / name), full_page=True)


def test_user_keeps_notes_and_snapshot_across_restart(tmp_path: Path) -> None:
    home = tmp_path / "desk"
    home.mkdir()
    desk = Desk(home)
    page_errors: list[str] = []
    try:
        url = desk.start()
        with sync_playwright() as play:
            before = _chrome_pids()
            try:
                browser = play.chromium.launch(
                    executable_path=CHROME,
                    headless=not HEADED,
                    slow_mo=250 if HEADED else 0,
                    args=["--start-fullscreen"] if HEADED else [],
                )
            except Exception as exc:  # pragma: no cover - Umgebung ohne Browser
                pytest.skip(f"kein Chromium verfügbar: {exc}")
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            _raise_chrome(before)
            page.bring_to_front()
            page.on("pageerror", lambda exc: page_errors.append(str(exc)))
            page.on("dialog", lambda dialog: dialog.accept())

            page.goto(url + "/lang/de", wait_until="networkidle")
            page.wait_for_function("() => window.Alpine !== undefined")
            expect(page.get_by_text("Wähle links einen Thread")).to_be_visible()
            expect(page.get_by_text("Keine Threads. Lege oben einen an.")).to_be_visible()
            _raise_chrome(before, "fenster-leer.png")
            _shot(page, "01-leer.png")

            page.locator("[data-new-thread]").click()
            title = page.locator("[data-new-title]")
            expect(title).to_be_visible()
            page.locator("#thread-list").get_by_role(
                "button", name="Anlegen", exact=True
            ).click()
            expect(page.get_by_text("Keine Threads. Lege oben einen an.")).to_be_visible()

            title.fill(TITLE)
            page.locator('#thread-list input[name="description"]').fill(DESCRIPTION)
            page.locator("#thread-list").get_by_role(
                "button", name="Anlegen", exact=True
            ).click()
            expect(page.locator(".thread-title")).to_have_text(TITLE)
            expect(page.locator('.desk-description input[name="text"]')).to_have_value(
                DESCRIPTION
            )
            expect(page.get_by_role("status")).to_contain_text(TITLE)
            _shot(page, "02-angelegt.png")

            notes = page.locator('#notes textarea[name="text"]')
            notes.fill(NOTE)
            page.locator("#notes").get_by_role(
                "button", name="Notiz speichern", exact=True
            ).click()
            expect(page.get_by_role("status")).to_have_text("Notiz gespeichert")
            expect(notes).to_have_value(NOTE)

            page.reload(wait_until="networkidle")
            notes = page.locator('#notes textarea[name="text"]')
            expect(notes).to_have_value(NOTE)
            expect(page.locator(".thread-title")).to_have_text(TITLE)
            _shot(page, "03-nach-neuladen.png")

            page.locator("[data-whiteboard-content]").fill(BOARD)
            page.locator("[data-whiteboard-submit]").click()
            expect(page.locator(".whiteboard-body")).to_have_text(BOARD)

            page.locator("[data-snapshot-label]").fill(LABEL)
            page.locator("#snapshots").get_by_role(
                "button", name="Speichern", exact=True
            ).click()
            expect(page.locator(".snap-label")).to_have_text(LABEL)

            notes = page.locator('#notes textarea[name="text"]')
            notes.fill(LATER)
            page.locator("#notes").get_by_role(
                "button", name="Notiz speichern", exact=True
            ).click()
            expect(notes).to_have_value(LATER)

            page.locator("#snapshots").get_by_role(
                "button", name="Laden", exact=True
            ).click()
            notes = page.locator('#notes textarea[name="text"]')
            expect(notes).to_have_value(NOTE)
            expect(page.locator(".whiteboard-body")).to_have_text(BOARD)
            expect(page.locator(".snap-label")).to_have_text(LABEL)
            _raise_chrome(before, "fenster-zwischenstand.png")
            _shot(page, "04-zwischenstand.png")
            browser.close()

        desk.stop()
        url = desk.start()
        with sync_playwright() as play:
            before = _chrome_pids()
            browser = play.chromium.launch(
                executable_path=CHROME,
                headless=not HEADED,
                slow_mo=250 if HEADED else 0,
                args=["--start-fullscreen"] if HEADED else [],
            )
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            _raise_chrome(before)
            page.bring_to_front()
            page.on("pageerror", lambda exc: page_errors.append(str(exc)))
            page.goto(url + "/", wait_until="networkidle")
            expect(page.locator(".thread-title")).to_have_text(TITLE)
            expect(page.locator('#notes textarea[name="text"]')).to_have_value(NOTE)
            expect(page.locator(".whiteboard-body")).to_have_text(BOARD)
            expect(page.get_by_text(LATER)).to_have_count(0)
            _raise_chrome(before, "fenster-neustart.png")
            _shot(page, "05-nach-neustart.png")
            browser.close()
    finally:
        desk.stop()
    assert page_errors == []


def _create(page, title: str) -> None:
    page.locator("[data-new-thread]").click()
    field = page.locator("[data-new-title]")
    expect(field).to_be_visible()
    field.fill(title)
    page.locator("#thread-list").get_by_role("button", name="Anlegen", exact=True).click()
    expect(page.locator(".thread-title").filter(has_text=title)).to_be_visible()


def test_user_renames_switches_archives_and_keeps_file_paths(tmp_path: Path) -> None:
    """TD-THREAD-02, TD-THREAD-04, TD-THREAD-05, TD-FILE-01, TD-HAUS-01, TD-HELP-01."""
    home = tmp_path / "desk"
    home.mkdir()
    desk = Desk(home)
    page_errors: list[str] = []
    try:
        url = desk.start()
        with sync_playwright() as play:
            before = _chrome_pids()
            try:
                browser = play.chromium.launch(
                    executable_path=CHROME,
                    headless=not HEADED,
                    slow_mo=200 if HEADED else 0,
                    args=["--start-fullscreen"] if HEADED else [],
                )
            except Exception as exc:  # pragma: no cover - Umgebung ohne Browser
                pytest.skip(f"kein Chromium verfügbar: {exc}")
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.bring_to_front()
            page.on("pageerror", lambda exc: page_errors.append(str(exc)))
            page.on("dialog", lambda dialog: dialog.accept())
            page.goto(url + "/lang/de", wait_until="networkidle")
            page.wait_for_function("() => window.Alpine !== undefined")
            _raise_chrome(before)

            _create(page, "Erster Thread")
            _create(page, "Zweiter Faden")
            page.locator(".thread-item", has_text="Erster Thread").click()
            expect(page.locator("h1")).to_have_text("Erster Thread")

            page.get_by_role("button", name="Umbenennen", exact=True).click()
            rename = page.locator('form[hx-post*="/rename"] input[name="title"]')
            expect(rename).to_be_visible()
            rename.fill("Erster umbenannt")
            page.locator('form[hx-post*="/rename"]').get_by_role(
                "button", name="OK", exact=True
            ).click()
            expect(page.locator("h1")).to_have_text("Erster umbenannt")
            expect(page.locator(".thread-title").filter(has_text="Erster umbenannt")).to_be_visible()

            path = "Notizen/Überblick.txt"
            page.locator('#files input[name="path"]').fill(path)
            page.locator("#files").get_by_role("button", name="Hinzufügen", exact=True).click()
            expect(page.locator("#files code")).to_have_text(path)
            page.locator("#files").get_by_role("button", name="Weg", exact=True).click()
            expect(page.locator("#files code")).to_have_count(0)
            page.locator("#files").scroll_into_view_if_needed()
            expect(page.locator("#files")).to_contain_text("Keine Dateipfade.")

            page.locator("[data-hausmeister]").scroll_into_view_if_needed()
            model = page.locator("[data-hausmeister-model]")
            expect(model).to_have_value("")
            expect(page.locator("[data-hausmeister]")).to_contain_text("Kein lokales Modell gewählt")
            page.locator("[data-hausmeister]").get_by_role(
                "button", name="Modell übernehmen", exact=True
            ).click()
            expect(model).to_have_value("")
            expect(page.locator("[data-hausmeister]")).to_contain_text("Kein lokales Modell gewählt")
            expect(page.get_by_role("status")).to_have_text("Kein lokales Modell gewählt")
            expect(page.locator(".banner-error:visible")).to_have_count(0)

            page.locator("[data-help-open]").click()
            expect(page.locator("#help")).to_be_visible()
            expect(page.locator("#help-title")).to_be_visible()
            page.keyboard.press("Escape")
            expect(page.locator("#help")).to_be_hidden()

            page.get_by_role("link", name="EN", exact=True).click()
            expect(page.locator("[data-new-thread]")).to_contain_text("New")
            page.get_by_role("link", name="DE", exact=True).click()
            expect(page.locator("[data-new-thread]")).to_contain_text("Neu")

            layout = page.evaluate(
                """() => {
                  const over = (sel) => {
                    const node = document.querySelector(sel);
                    if (!node) return null;
                    return node.scrollHeight > node.clientHeight + 1;
                  };
                  return {
                    page: document.documentElement.scrollHeight > document.documentElement.clientHeight + 1,
                    notes: over('.desk-notes'),
                    side: over('.desk-side'),
                  };
                }"""
            )
            if SHOTS:
                Path(SHOTS, "layout.txt").write_text(str(layout), encoding="utf-8")
            assert layout["page"] is False, layout

            page.locator(".thread-item", has_text="Zweiter Faden").click()
            expect(page.locator("h1")).to_have_text("Zweiter Faden")
            page.get_by_role("button", name="Archivieren", exact=True).click()
            expect(page.locator(".thread-title").filter(has_text="Zweiter Faden")).to_have_count(0)
            expect(page.locator(".thread-title").filter(has_text="Erster umbenannt")).to_be_visible()
            expect(page.get_by_text("Wähle links einen Thread")).to_be_visible()
            stored = "\n".join(
                item.read_text(encoding="utf-8")
                for item in home.rglob("*.json")
                if item.is_file()
            )
            assert "Zweiter Faden" in stored
            _raise_chrome(before, "fenster-archiv.png")
            _shot(page, "06-archiv.png")
            browser.close()
    finally:
        desk.stop()
    assert page_errors == []
