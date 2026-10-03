"""Browserabnahme der Schreibtisch-Kernabläufe.

Ablaufkennungen: TD-START-01, TD-THREAD-01, TD-NOTE-01, TD-SNAP-01.
Der Nutzer arbeitet nur mit den angebotenen Schaltflächen. Der Server ist ein
eigener Prozess. Neuladen und ein zweiter Start lesen denselben synthetischen
Arbeitsbereich. Ein Zwischenstand setzt Notizen zurück und lässt den Verlauf
stehen.
"""

from __future__ import annotations

import os
import re
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
# Sichtbares Fenster: jede Aktion wartet 1,5 Sekunden. Kopflos bleibt schnell.
PACE_MS = 1500

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


def _launch(play, extra_args: list[str] | None = None):
    args = list(extra_args or [])
    if HEADED:
        args.append("--start-fullscreen")
    try:
        return play.chromium.launch(
            executable_path=CHROME,
            headless=not HEADED,
            slow_mo=PACE_MS if HEADED else 0,
            args=args,
        )
    except Exception as exc:  # pragma: no cover - Umgebung ohne Browser
        pytest.skip(f"kein Chromium verfügbar: {exc}")


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
            browser = _launch(play)
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
            browser = _launch(play)
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
    page.wait_for_function(
        "() => { const root = document.querySelector('.new-thread');"
        " return !!(root && root._x_dataStack); }"
    )
    button = page.locator("[data-new-thread]")
    field = page.locator("[data-new-title]")
    button.click()
    # Ein Klick während des Vollbildwechsels trifft die Schaltfläche manchmal nicht.
    if not field.is_visible():
        button.evaluate("el => el.click()")
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
            browser = _launch(play)
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


def _append(page, actor: str, content: str, kind: str, next_step: str = "") -> None:
    form = page.locator("[data-whiteboard]")
    form.locator("[data-whiteboard-actor]").fill(actor)
    form.locator("[data-whiteboard-type]").select_option(kind)
    form.locator("[data-whiteboard-content]").fill(content)
    form.locator("[data-whiteboard-next]").fill(next_step)
    form.locator("[data-whiteboard-submit]").click()
    expect(page.get_by_role("status")).to_have_text("Beitrag angehängt")


def test_user_edits_description_status_and_whiteboard_order(tmp_path: Path) -> None:
    """TD-THREAD-03, TD-BOARD-02. Konflikt ohne externe Kennung hat keine Schaltfläche."""
    home = tmp_path / "desk"
    home.mkdir()
    desk = Desk(home)
    page_errors: list[str] = []
    first = "Erster Verlauf ÄÖÜ"
    second = "Zweiter Verlauf, noch einmal"
    try:
        url = desk.start()
        with sync_playwright() as play:
            before = _chrome_pids()
            browser = _launch(play)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.bring_to_front()
            page.on("pageerror", lambda exc: page_errors.append(str(exc)))
            page.on("dialog", lambda dialog: dialog.accept())
            page.goto(url + "/lang/de", wait_until="networkidle")
            page.wait_for_function("() => window.Alpine !== undefined")
            _raise_chrome(before)

            page.locator("[data-new-thread]").click()
            page.locator("[data-new-title]").fill("Statusfaden")
            page.locator('#thread-list input[name="description"]').fill("Erster Zweck")
            page.locator("#thread-list").get_by_role("button", name="Anlegen", exact=True).click()
            expect(page.locator("h1")).to_have_text("Statusfaden")
            description = page.locator('.desk-description input[name="text"]')
            expect(description).to_have_value("Erster Zweck")
            expect(page.locator(".desk-status button.is-on")).to_have_text("idea")
            expect(page.locator("[data-whiteboard-empty]")).to_have_text("Noch kein Beitrag.")

            page.locator("[data-whiteboard-submit]").click()
            expect(page.locator("[data-whiteboard-entry]")).to_have_count(0)

            description.fill("Neuer Zweck mit ÄÖÜ")
            page.locator(".desk-description").get_by_role(
                "button", name="Speichern", exact=True
            ).click()
            expect(page.get_by_role("status")).to_have_text("Beschreibung gespeichert")
            expect(description).to_have_value("Neuer Zweck mit ÄÖÜ")

            for name in ("active", "paused", "done"):
                page.locator(".desk-status").get_by_role("button", name=name, exact=True).click()
                expect(page.locator(".desk-status button.is-on")).to_have_text(name)
                expect(page.locator(".detail-head .status")).to_have_text(name)
                expect(page.locator(".thread-item.is-current .status")).to_have_text(name)
                expect(page.get_by_role("status")).to_have_text(f"Status: {name}")
            page.locator(".desk-status").get_by_role("button", name="done", exact=True).click()
            expect(page.locator(".desk-status button.is-on")).to_have_text("done")
            expect(page.locator(".banner-error:visible")).to_have_count(0)

            _append(page, "Prüferin", first, "decision", "Danach prüfen")
            expect(page.locator("[data-whiteboard-entry]")).to_have_count(1)
            expect(page.locator(".whiteboard-body")).to_have_text(first)
            expect(page.locator(".whiteboard-meta")).to_contain_text("Prüferin")
            expect(page.locator(".whiteboard-meta")).to_contain_text("Entscheidung")
            expect(page.locator("[data-stand-actor]")).to_have_text("Prüferin")
            expect(page.locator("[data-stand-next]")).to_have_text("Danach prüfen")
            expect(page.locator("[data-stand-last]")).to_have_text(first)
            expect(page.locator("[data-stand-status]")).to_have_text("done")

            _append(page, "Zweite Person", second, "problem", "")
            _append(page, "Zweite Person", second, "problem", "")
            bodies = page.locator(".whiteboard-body")
            expect(bodies).to_have_count(3)
            expect(bodies.nth(0)).to_have_text(first)
            expect(bodies.nth(1)).to_have_text(second)
            expect(bodies.nth(2)).to_have_text(second)
            metas = page.locator(".whiteboard-meta")
            expect(metas.nth(1)).to_contain_text("Zweite Person")
            expect(metas.nth(1)).to_contain_text("Problem")
            expect(metas.nth(2)).to_contain_text("Zweite Person")
            ids = page.locator("[data-whiteboard-entry]").evaluate_all(
                "nodes => nodes.map(node => node.getAttribute('data-entry-id'))"
            )
            assert len(set(ids)) == 3
            expect(page.locator("[data-stand-actor]")).to_have_text("Zweite Person")
            expect(page.locator("[data-stand-last]")).to_have_text(second)
            expect(page.locator("[data-stand-next]")).to_have_text("Danach prüfen")

            page.reload(wait_until="networkidle")
            page.wait_for_function("() => window.Alpine !== undefined")
            expect(page.locator('.desk-description input[name="text"]')).to_have_value(
                "Neuer Zweck mit ÄÖÜ"
            )
            expect(page.locator(".desk-status button.is-on")).to_have_text("done")
            expect(page.locator(".whiteboard-body")).to_have_count(3)
            expect(page.locator(".whiteboard-body").nth(0)).to_have_text(first)
            expect(page.locator(".whiteboard-body").nth(2)).to_have_text(second)

            _create(page, "Nur zum Wechseln")
            page.locator(".thread-item", has_text="Statusfaden").click()
            expect(page.locator("h1")).to_have_text("Statusfaden")
            expect(page.locator('.desk-description input[name="text"]')).to_have_value(
                "Neuer Zweck mit ÄÖÜ"
            )
            expect(page.locator(".desk-status button.is-on")).to_have_text("done")
            expect(page.locator(".whiteboard-body")).to_have_count(3)
            _raise_chrome(before, "fenster-status.png")
            _shot(page, "07-status.png")
            browser.close()
    finally:
        desk.stop()
    assert page_errors == []


def test_user_creates_filters_and_opens_knowledge_on_the_map(tmp_path: Path) -> None:
    """TD-KNOW-01. Knoten, Filter, Verbindung und derselbe Knoten auf der Karte."""
    home = tmp_path / "desk"
    home.mkdir()
    desk = Desk(home)
    page_errors: list[str] = []
    title = "Projekt ÄÖÜ"
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
            page.get_by_role("link", name="Wissenspool", exact=True).click()
            expect(page.locator("h1")).to_have_text("Wissenspool")
            expect(page.get_by_text("Noch keine Knoten. Der erste Knoten kann ein Projekt sein.")).to_be_visible()
            expect(page.get_by_text("Für eine Verbindung werden mindestens zwei Knoten benötigt.")).to_be_visible()

            form = page.locator('form[action="/knowledge/nodes"]')
            form.get_by_role("button", name="Knoten speichern", exact=True).click()
            expect(page.locator(".node-row")).to_have_count(0)

            form.locator('select[name="kind"]').select_option("project")
            form.locator('input[name="title"]').fill(title)
            form.locator('select[name="status"]').select_option("idea")
            form.locator('textarea[name="details"]').fill("Sichtbarer Zweck")
            form.get_by_role("button", name="Knoten speichern", exact=True).click()
            row = page.locator(".node-row", has_text=title)
            expect(row).to_be_visible()
            expect(row).to_contain_text("Sichtbarer Zweck")
            expect(row.locator(".status")).to_have_text("idea")

            filters = page.locator("form.knowledge-filter")
            filters.locator('select[name="kind"]').select_option("task")
            filters.get_by_role("button", name="Filtern", exact=True).click()
            expect(page.locator(".node-row")).to_have_count(0)
            expect(page).to_have_url(re.compile(r"kind=task"))
            page.get_by_role("link", name="Zurücksetzen", exact=True).click()
            expect(page.locator(".node-row", has_text=title)).to_be_visible()

            form = page.locator('form[action="/knowledge/nodes"]')
            form.locator('select[name="kind"]').select_option("person")
            form.locator('input[name="title"]').fill("Prüferin")
            form.locator('select[name="status"]').select_option("active")
            form.get_by_role("button", name="Knoten speichern", exact=True).click()
            expect(page.locator(".node-row")).to_have_count(2)

            relation = page.locator('form[action="/knowledge/relations"]')
            relation.locator('select[name="source_id"]').select_option(label=f"{title} · Projekt")
            relation.locator('select[name="kind"]').select_option("contains")
            relation.locator('select[name="target_id"]').select_option(label="Prüferin · Person")
            relation.get_by_role("button", name="Linie speichern", exact=True).click()
            expect(page.locator(".relation-row")).to_have_count(1)
            expect(page.locator(".relation-row")).to_contain_text("contains")

            page.reload(wait_until="networkidle")
            expect(page.locator(".node-row")).to_have_count(2)
            expect(page.locator(".relation-row")).to_have_count(1)

            page.get_by_role("link", name="Karte", exact=True).click()
            expect(page.locator("[data-map-canvas]")).to_be_visible()
            expect(page.locator("[data-map-world]")).to_contain_text(title)
            expect(page.locator("[data-map-world]")).to_contain_text("Prüferin")
            page.locator(f'[data-map-world] [aria-label^="{title},"]').click()
            expect(page.locator("[data-map-detail-title]")).to_have_text(title)
            expect(page.locator("[data-map-detail-text]")).to_have_text("Sichtbarer Zweck")
            _raise_chrome(before, "fenster-wissen.png")
            _shot(page, "08-wissen.png")
            browser.close()
    finally:
        desk.stop()
    assert page_errors == []


def test_user_switches_plain_and_expert_wording(tmp_path: Path) -> None:
    """TD-I18N-01. Klartext und Fachsprache, danach dieselbe Ebene auf Englisch."""
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
            _create(page, "Sprachebene")
            heading = page.locator("#snapshots h3")
            expect(heading).to_have_text("Zwischenstände")
            page.get_by_role("link", name="Fachsprache", exact=True).click()
            expect(heading).to_have_text("Snapshots")
            expect(page.locator("#snapshots .muted").first).to_contain_text("Snapshot-ID")
            page.get_by_role("link", name="Klartext", exact=True).click()
            expect(heading).to_have_text("Zwischenstände")
            page.get_by_role("link", name="EN", exact=True).click()
            expect(heading).to_have_text("Saved states")
            page.get_by_role("link", name="Expert", exact=True).click()
            expect(heading).to_have_text("Snapshots")
            page.get_by_role("link", name="Plain", exact=True).click()
            expect(heading).to_have_text("Saved states")
            page.get_by_role("link", name="DE", exact=True).click()
            expect(heading).to_have_text("Zwischenstände")
            expect(page.locator(".banner-error:visible")).to_have_count(0)
            _raise_chrome(before, "fenster-sprache.png")
            _shot(page, "09-sprache.png")
            browser.close()
    finally:
        desk.stop()
    assert page_errors == []


def _export(home: Path, fmt: str, target: Path) -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    env["THREADDESK_HOME"] = str(home)
    env.pop("THREADDESK_STORAGE", None)
    completed = subprocess.run(
        [
            sys.executable, "-m", "threaddesk.ui.cli", "graph", "--export",
            "--format", fmt, "--include-private", "--output", str(target),
        ],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_user_opens_graph_json_and_exports_private_knowledge(tmp_path: Path) -> None:
    """TD-EXPORT-01. Graph-JSON im Schreibtisch, dazu die vorhandenen Textformate."""
    home = tmp_path / "desk"
    home.mkdir()
    desk = Desk(home)
    page_errors: list[str] = []
    title = "Export ÄÖÜ"
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
            page.get_by_role("link", name="Wissenspool", exact=True).click()
            form = page.locator('form[action="/knowledge/nodes"]')
            form.locator('select[name="kind"]').select_option("project")
            form.locator('input[name="title"]').fill(title)
            form.locator('textarea[name="details"]').fill("Sichtbarer Export")
            form.get_by_role("button", name="Knoten speichern", exact=True).click()
            expect(page.locator(".node-row", has_text=title)).to_be_visible()
            page.get_by_role("link", name="Graph-JSON", exact=True).click()
            expect(page.locator("body")).to_contain_text(title)
            expect(page.locator("body")).to_contain_text("threaddesk.graph.v1")
            for fmt, name in (("json", "export.json"), ("markdown", "export.md"), ("csv", "export.csv")):
                target = tmp_path / name
                _export(home, fmt, target)
                assert title in target.read_text(encoding="utf-8")
            _raise_chrome(before, "fenster-export.png")
            _shot(page, "12-export.png")
            browser.close()
    finally:
        desk.stop()
    assert page_errors == []


def test_user_switches_the_housekeeper_without_a_model(tmp_path: Path) -> None:
    """TD-HAUS-01. Ein, aus, fehlendes Modell, wartender Auftrag. Kein Modellergebnis."""
    home = tmp_path / "desk"
    home.mkdir()
    desk = Desk(home)
    page_errors: list[str] = []
    order = "Nur vormerken, nicht ausführen"
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
            _create(page, "Hausmeister")
            section = page.locator("[data-hausmeister]")
            section.scroll_into_view_if_needed()
            probe = section.inner_text()
            assert (
                "Ollama ist lokal erreichbar" in probe
                or "Ollama ist nicht erreichbar" in probe
            )
            section.get_by_role("button", name="Einschalten", exact=True).click()
            expect(section.get_by_role("button", name="Ausschalten", exact=True)).to_be_visible()
            expect(page.locator("[data-hausmeister-order]")).to_be_visible()
            expect(page.get_by_role("status")).to_have_text("Einschalten")
            page.locator("[data-hausmeister-run]").click()
            expect(page.get_by_role("alert")).to_have_text("Auftrag nicht ausgeführt")
            expect(page.locator("[data-hausmeister-entry]")).to_have_count(0)
            page.locator("[data-hausmeister-order]").fill(order)
            page.locator("[data-hausmeister-run]").click()
            expect(page.get_by_role("alert")).to_have_text("Kein lokales Modell gewählt")
            expect(page.locator("h1")).to_have_text("Hausmeister")
            page.locator("[data-hausmeister-order]").fill(order)
            page.locator("[data-hausmeister-later]").click()
            expect(page.get_by_role("status")).to_have_text("Auftrag wartet")
            queued = (home / "hausmeister-queue.json").read_text(encoding="utf-8")
            assert order in queued
            page.locator("[data-hausmeister]").get_by_role(
                "button", name="Ausschalten", exact=True
            ).click()
            expect(page.locator("[data-hausmeister-order]")).to_have_count(0)
            expect(page.locator("[data-hausmeister]").get_by_role(
                "button", name="Einschalten", exact=True
            )).to_be_visible()
            expect(page.get_by_role("status")).to_have_text("Ausschalten")
            _raise_chrome(before, "fenster-hausmeister.png")
            _shot(page, "13-hausmeister.png")
            browser.close()
    finally:
        desk.stop()
    assert page_errors == []


def test_user_runs_the_housekeeper_on_an_installed_model(tmp_path: Path) -> None:
    """TD-HAUS-01. Echter lokaler Auftrag nur mit THREADDESK_HAUSMEISTER_LIVE=1.

    Die normale Suite setzt die Variable nicht und ruft Ollama dafür nicht auf.
    Ein Lauf beweist keine Antwortqualität.
    """
    if os.environ.get("THREADDESK_HAUSMEISTER_LIVE") != "1":
        return
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


def _sentence(key: str, language: str) -> str:
    from threaddesk.core import i18n

    return i18n.translate(key, language)


def _shows(page, language: str, *keys: str) -> None:
    for key in keys:
        expect(page.locator("body")).to_contain_text(_sentence(key, language))


def _hides(page, language: str, *keys: str) -> None:
    for key in keys:
        expect(page.locator("body")).not_to_contain_text(_sentence(key, language))


def _register_name(page, language: str) -> None:
    """nav.register ist der zugängliche Name der Ebene, kein eigener Satz im Text."""
    expect(
        page.get_by_role("navigation", name=_sentence("nav.register", language))
    ).to_be_visible()


def test_user_reads_the_main_pages_in_both_languages(tmp_path: Path) -> None:
    """TD-I18N-01. Sichtbare Sätze auf Schreibtisch, Hilfe, Wissen, Karte und Sicherung."""
    home = tmp_path / "desk"
    home.mkdir()
    desk = Desk(home)
    page_errors: list[str] = []
    desk_keys = (
        "app.tagline", "app.local_note", "nav.knowledge", "data.nav", "nav.map",
        "register.plain", "register.expert", "help.open",
        "list.new", "list.empty", "detail.pick", "detail.or_new",
        "gate.title", "room.title", "room.create",
    )
    help_keys = (
        "help.title", "help.new_thread", "help.next_prev", "help.pick_thread",
        "help.snapshot_field", "help.microphone", "help.save_form",
        "help.this_help", "help.no_agent",
    )
    knowledge_keys = (
        "knowledge.lead", "knowledge.graph_json", "knowledge.save_node",
        "knowledge.filter", "knowledge.reset",
    )
    map_keys = (
        "map.title", "map.eyebrow", "map.fit", "map.no_selection",
        "map.legend_circle", "map.legend_rect", "map.legend_risk", "map.legend_ai",
    )
    data_keys = (
        "data.title", "data.intro", "data.download", "data.file",
        "data.confirm", "data.restore", "data.private",
    )
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
            expect(page.locator("html")).to_have_attribute("lang", "de")
            _register_name(page, "de")
            _shows(page, "de", *desk_keys)
            expect(page.locator("[data-room-name]")).to_have_attribute(
                "placeholder", _sentence("room.name", "de")
            )
            page.locator("[data-help-open]").click()
            help_box = page.locator("#help")
            expect(help_box).to_be_visible()
            for key in help_keys:
                expect(help_box).to_contain_text(_sentence(key, "de"))
            page.keyboard.press("Escape")
            expect(help_box).to_be_hidden()

            page.get_by_role("link", name="Wissenspool", exact=True).click()
            _shows(page, "de", *knowledge_keys)
            page.get_by_role("link", name="Karte", exact=True).click()
            _shows(page, "de", *map_keys)
            page.get_by_role("link", name="Daten", exact=True).click()
            _shows(page, "de", *data_keys)

            page.get_by_role("link", name="EN", exact=True).click()
            expect(page.locator("html")).to_have_attribute("lang", "en")
            _shows(page, "en", *data_keys)
            _hides(
                page, "de",
                "data.title", "data.intro", "app.tagline", "knowledge.save_node",
                "map.title", "help.no_agent", "detail.pick",
            )
            page.get_by_role("link", name="Map", exact=True).click()
            _shows(page, "en", *map_keys)
            page.get_by_role("link", name="Knowledge", exact=True).click()
            _shows(page, "en", *knowledge_keys)
            page.get_by_role("link", name="Threads", exact=True).click()
            _register_name(page, "en")
            _shows(page, "en", *desk_keys)
            expect(page.locator("[data-room-name]")).to_have_attribute(
                "placeholder", _sentence("room.name", "en")
            )
            page.locator("[data-help-open]").click()
            expect(help_box).to_be_visible()
            for key in help_keys:
                expect(help_box).to_contain_text(_sentence(key, "en"))
            _raise_chrome(before, "fenster-saetze.png")
            _shot(page, "16-saetze.png")
            page.keyboard.press("Escape")
            expect(help_box).to_be_hidden()
            browser.close()
    finally:
        desk.stop()
    assert page_errors == []


def _notice(page, text: str) -> None:
    banner = page.locator(".toast-stack .banner-ok")
    expect(banner).to_be_visible()
    expect(banner).to_have_text(text)


def test_user_reads_action_notices_in_english(tmp_path: Path) -> None:
    """TD-I18N-01. Hinweise nach Anlegen, Beschreibung, Notiz, Verlauf und Pfad."""
    home = tmp_path / "desk"
    home.mkdir()
    desk = Desk(home)
    page_errors: list[str] = []
    title = "Notice ÄÖÜ"
    try:
        url = desk.start()
        with sync_playwright() as play:
            before = _chrome_pids()
            browser = _launch(play)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.bring_to_front()
            page.on("pageerror", lambda exc: page_errors.append(str(exc)))
            page.goto(url + "/lang/en", wait_until="networkidle")
            page.wait_for_function("() => window.Alpine !== undefined")
            _raise_chrome(before)
            expect(page.locator("html")).to_have_attribute("lang", "en")

            page.wait_for_function(
                "() => { const root = document.querySelector('.new-thread');"
                " return !!(root && root._x_dataStack); }"
            )
            button = page.locator("[data-new-thread]")
            field = page.locator("[data-new-title]")
            button.click()
            if not field.is_visible():
                button.evaluate("el => el.click()")
            expect(field).to_be_visible()
            field.fill(title)
            page.locator("#thread-list").get_by_role(
                "button", name=_sentence("list.create", "en"), exact=True
            ).click()
            _notice(page, _sentence("ui.created", "en").format(title=title))
            expect(page.locator("h1")).to_have_text(title)
            expect(page.locator("body")).not_to_contain_text(
                _sentence("ui.created", "de").format(title=title)
            )

            expect(page.locator("#files")).to_contain_text(_sentence("files.hint", "en"))
            expect(page.locator("#files")).to_contain_text(_sentence("files.empty", "en"))
            _hides(page, "de", "files.hint", "files.empty")

            page.locator('.desk-description input[name="text"]').fill("A visible purpose")
            page.locator(".desk-description").get_by_role(
                "button", name=_sentence("detail.save", "en"), exact=True
            ).click()
            _notice(page, _sentence("ui.description_saved", "en"))
            _hides(page, "de", "ui.description_saved")

            page.locator("#notes textarea[name='text']").fill("A note that stays")
            page.locator("#notes").get_by_role(
                "button", name=_sentence("notes.save", "en"), exact=True
            ).click()
            _notice(page, _sentence("ui.note_saved", "en"))
            expect(page.locator("#notes textarea[name='text']")).to_have_value(
                "A note that stays"
            )
            _hides(page, "de", "ui.note_saved")

            form = page.locator("[data-whiteboard]")
            form.locator("[data-whiteboard-actor]").fill("Checker")
            form.locator("[data-whiteboard-type]").select_option("decision")
            form.locator("[data-whiteboard-content]").fill("English entry")
            form.locator("[data-whiteboard-submit]").click()
            _notice(page, _sentence("ui.whiteboard_saved", "en"))
            expect(page.locator(".whiteboard-body")).to_have_text("English entry")
            _hides(page, "de", "ui.whiteboard_saved")

            page.locator("#files input[name='path']").fill("src/notice.py")
            page.locator("#files").get_by_role(
                "button", name=_sentence("files.add", "en"), exact=True
            ).click()
            _notice(page, _sentence("ui.file_added", "en").format(path="src/notice.py"))
            expect(page.locator("#files code")).to_have_text("src/notice.py")
            expect(page.locator("body")).not_to_contain_text(
                _sentence("ui.file_added", "de").format(path="src/notice.py")
            )

            _raise_chrome(before, "fenster-hinweise.png")
            _shot(page, "17-hinweise.png")
            browser.close()
    finally:
        desk.stop()
    assert page_errors == []


def _alert(page, text: str) -> None:
    banner = page.locator(".toast-stack .banner-error")
    expect(banner).to_be_visible()
    expect(banner).to_have_text(text)


def test_user_reads_housekeeper_phases_in_english(tmp_path: Path) -> None:
    """TD-HAUS-01. Englische Hausmeister-Sätze. Kein Auftrag an Ollama.

    „Waiting for a job“ steht nur, wenn ein bereits gelistetes Modell
    gespeichert ist und kein Auftrag wartet. „Working“ und „Paused“
    brauchen einen laufenden Auftrag und bleiben in diesem Lauf weg.
    """
    home = tmp_path / "desk"
    home.mkdir()
    desk = Desk(home)
    page_errors: list[str] = []
    title = "Housekeeper"
    order = "Remember this, do not run it"
    phase_keys = (
        "hausmeister.phase.waiting_for_order",
        "hausmeister.phase.waiting_for_quiet",
        "hausmeister.phase.working",
        "hausmeister.phase.paused",
    )
    try:
        url = desk.start()
        with sync_playwright() as play:
            before = _chrome_pids()
            browser = _launch(play, ["--disable-features=Translate"])
            page = browser.new_page(
                viewport={"width": 1440, "height": 900},
                locale="en-US",
            )
            page.bring_to_front()
            page.on("pageerror", lambda exc: page_errors.append(str(exc)))
            page.goto(url + "/lang/en", wait_until="networkidle")
            page.wait_for_function("() => window.Alpine !== undefined")
            _raise_chrome(before)
            expect(page.locator("html")).to_have_attribute("lang", "en")
            page.wait_for_function(
                "() => { const root = document.querySelector('.new-thread');"
                " return !!(root && root._x_dataStack); }"
            )
            button = page.locator("[data-new-thread]")
            field = page.locator("[data-new-title]")
            button.click()
            if not field.is_visible():
                button.evaluate("el => el.click()")
            expect(field).to_be_visible()
            field.fill(title)
            page.locator("#thread-list").get_by_role(
                "button", name=_sentence("list.create", "en"), exact=True
            ).click()
            expect(page.locator("h1")).to_have_text(title)

            section = page.locator("[data-hausmeister]")
            section.scroll_into_view_if_needed()
            phase = page.locator("[data-hausmeister-phase]")
            probe = section.inner_text()
            reachable = _sentence("hausmeister.reachable", "en")
            unreachable = _sentence("hausmeister.unreachable", "en")
            assert reachable in probe or unreachable in probe
            ollama_up = reachable in probe
            expect(phase).to_have_attribute("data-hausmeister-phase", "off")
            for key in phase_keys:
                expect(phase).not_to_contain_text(_sentence(key, "en"))
            expect(page.locator("[data-hausmeister-model]")).to_have_value("")
            expect(page.locator("[data-hausmeister-model] option:checked")).to_have_text(
                _sentence("hausmeister.model_none", "en")
            )
            expect(section).to_contain_text(_sentence("hausmeister.title", "en"))
            expect(section).to_contain_text(_sentence("hausmeister.no_model", "en"))
            expect(section.get_by_role(
                "button", name=_sentence("hausmeister.turn_on", "en"), exact=True
            )).to_be_visible()
            _hides(
                page, "de",
                "hausmeister.title", "hausmeister.reachable", "hausmeister.unreachable",
                "hausmeister.no_model", "hausmeister.model_none", "hausmeister.turn_on",
                "hausmeister.turn_off", "hausmeister.use_model", "hausmeister.run",
                "hausmeister.later", "hausmeister.failed", "hausmeister.queued",
                "hausmeister.phase.waiting_for_order", "hausmeister.phase.waiting_for_quiet",
                "hausmeister.phase.working", "hausmeister.phase.paused",
                "hausmeister.disabled",
            )

            names = page.locator("[data-hausmeister-model] option").evaluate_all(
                "els => els.map((el) => el.value).filter(Boolean)"
            )
            if ollama_up and names:
                page.locator("[data-hausmeister-model]").select_option(names[0])
                section.get_by_role(
                    "button", name=_sentence("hausmeister.use_model", "en"), exact=True
                ).click()
                _notice(page, _sentence("hausmeister.use_model", "en"))
                expect(phase).to_have_attribute("data-hausmeister-phase", "off")
                expect(section).not_to_contain_text(_sentence("hausmeister.no_model", "en"))
                section.get_by_role(
                    "button", name=_sentence("hausmeister.turn_on", "en"), exact=True
                ).click()
                _notice(page, _sentence("hausmeister.turn_on", "en"))
                expect(phase).to_have_attribute("data-hausmeister-phase", "waiting_for_order")
                expect(phase).to_contain_text(_sentence("hausmeister.reachable", "en"))
                expect(phase).to_contain_text(
                    _sentence("hausmeister.phase.waiting_for_order", "en")
                )
                for key in phase_keys[1:]:
                    expect(phase).not_to_contain_text(_sentence(key, "en"))
                _raise_chrome(before, "fenster-hausmeister-en.png")
                _shot(page, "19-hausmeister.png")
                page.locator("[data-hausmeister-model]").select_option("")
                section.get_by_role(
                    "button", name=_sentence("hausmeister.use_model", "en"), exact=True
                ).click()
                _notice(page, _sentence("hausmeister.no_model", "en"))
                expect(phase).to_have_attribute("data-hausmeister-phase", "no_model")
                expect(phase).not_to_contain_text(
                    _sentence("hausmeister.phase.waiting_for_order", "en")
                )
            else:
                section.get_by_role(
                    "button", name=_sentence("hausmeister.turn_on", "en"), exact=True
                ).click()
                _notice(page, _sentence("hausmeister.turn_on", "en"))
                expect(phase).to_have_attribute(
                    "data-hausmeister-phase",
                    "no_model" if ollama_up else "ollama_down",
                )
                for key in phase_keys:
                    expect(phase).not_to_contain_text(_sentence(key, "en"))
                _raise_chrome(before, "fenster-hausmeister-en.png")
                _shot(page, "19-hausmeister.png")

            expect(page.locator("[data-hausmeister-order]")).to_be_visible()
            expect(page.locator("[data-hausmeister-order]")).to_have_attribute(
                "placeholder", _sentence("hausmeister.order_placeholder", "en")
            )
            expect(section.get_by_role(
                "button", name=_sentence("hausmeister.run", "en"), exact=True
            )).to_be_visible()
            expect(section.get_by_role(
                "button", name=_sentence("hausmeister.later", "en"), exact=True
            )).to_be_visible()
            page.locator("[data-hausmeister-run]").click()
            _alert(page, _sentence("hausmeister.failed", "en"))
            expect(page.locator("[data-hausmeister-entry]")).to_have_count(0)
            page.locator("[data-hausmeister-order]").fill(order)
            page.locator("[data-hausmeister-run]").click()
            _alert(page, _sentence("hausmeister.no_model", "en"))
            expect(page.locator("h1")).to_have_text(title)
            expect(page.locator("[data-hausmeister-entry]")).to_have_count(0)
            page.locator("[data-hausmeister-order]").fill(order)
            page.locator("[data-hausmeister-later]").click()
            _notice(page, _sentence("hausmeister.queued", "en"))
            queued = (home / "hausmeister-queue.json").read_text(encoding="utf-8")
            assert order in queued
            expect(phase).to_have_attribute(
                "data-hausmeister-phase",
                "no_model" if ollama_up else "ollama_down",
            )
            for key in phase_keys:
                expect(phase).not_to_contain_text(_sentence(key, "en"))
            section.get_by_role(
                "button", name=_sentence("hausmeister.turn_off", "en"), exact=True
            ).click()
            expect(page.locator("[data-hausmeister-order]")).to_have_count(0)
            expect(section.get_by_role(
                "button", name=_sentence("hausmeister.turn_on", "en"), exact=True
            )).to_be_visible()
            _notice(page, _sentence("hausmeister.turn_off", "en"))
            expect(phase).to_have_attribute("data-hausmeister-phase", "off")
            browser.close()
    finally:
        desk.stop()
    assert page_errors == []


def _create_en(page, title: str) -> None:
    page.wait_for_function(
        "() => { const root = document.querySelector('.new-thread');"
        " return !!(root && root._x_dataStack); }"
    )
    button = page.locator("[data-new-thread]")
    field = page.locator("[data-new-title]")
    button.click()
    if not field.is_visible():
        button.evaluate("el => el.click()")
    expect(field).to_be_visible()
    field.fill(title)
    page.locator("#thread-list").get_by_role(
        "button", name=_sentence("list.create", "en"), exact=True
    ).click()
    expect(page.locator("h1")).to_have_text(title)


def test_user_reads_rename_and_archive_in_english(tmp_path: Path) -> None:
    """TD-I18N-01. Englische Hinweise für Umbenennen und Archiv. Keine Rückholtaste."""
    home = tmp_path / "desk"
    home.mkdir()
    desk = Desk(home)
    page_errors: list[str] = []
    dialogs: list[str] = []
    first = "First thread"
    renamed = "First renamed"
    second = "Second thread"
    try:
        url = desk.start()
        with sync_playwright() as play:
            before = _chrome_pids()
            browser = _launch(play, ["--disable-features=Translate"])
            page = browser.new_page(
                viewport={"width": 1440, "height": 900},
                locale="en-US",
            )
            page.bring_to_front()
            page.on("pageerror", lambda exc: page_errors.append(str(exc)))
            page.on(
                "dialog",
                lambda dialog: (dialogs.append(dialog.message), dialog.accept()),
            )
            page.goto(url + "/lang/en", wait_until="networkidle")
            page.wait_for_function("() => window.Alpine !== undefined")
            _raise_chrome(before)
            expect(page.locator("html")).to_have_attribute("lang", "en")
            _create_en(page, first)
            _create_en(page, second)
            page.locator(".thread-item", has_text=first).click()
            expect(page.locator("h1")).to_have_text(first)
            page.get_by_role(
                "button", name=_sentence("detail.rename", "en"), exact=True
            ).click()
            rename = page.locator('form[hx-post*="/rename"] input[name="title"]')
            expect(rename).to_be_visible()
            rename.fill(renamed)
            page.locator('form[hx-post*="/rename"]').get_by_role(
                "button", name=_sentence("detail.ok", "en"), exact=True
            ).click()
            expect(page.locator("h1")).to_have_text(renamed)
            expect(page.locator(".thread-title").filter(has_text=renamed)).to_be_visible()
            _notice(page, _sentence("ui.renamed", "en").format(title=renamed))
            expect(page.locator("body")).not_to_contain_text(
                _sentence("ui.renamed", "de").format(title=renamed)
            )
            _hides(page, "de", "detail.rename", "detail.archive")
            _shot(page, "20-umbenennen.png")

            page.locator(".thread-item", has_text=second).click()
            expect(page.locator("h1")).to_have_text(second)
            page.get_by_role(
                "button", name=_sentence("detail.archive", "en"), exact=True
            ).click()
            assert dialogs == [_sentence("detail.confirm_archive", "en")]
            expect(page.locator(".thread-title").filter(has_text=second)).to_have_count(0)
            expect(page.locator(".thread-title").filter(has_text=renamed)).to_be_visible()
            expect(page.get_by_text(_sentence("detail.pick", "en"))).to_be_visible()
            _notice(page, _sentence("ui.archived", "en").format(title=second))
            expect(page.locator("body")).not_to_contain_text(
                _sentence("ui.archived", "de").format(title=second)
            )
            expect(page.locator("body")).not_to_contain_text(
                _sentence("detail.confirm_archive", "de")
            )
            _hides(page, "de", "detail.pick")
            stored = "\n".join(
                item.read_text(encoding="utf-8")
                for item in home.rglob("*.json")
                if item.is_file()
            )
            assert second in stored
            _raise_chrome(before, "fenster-archiv-en.png")
            _shot(page, "21-archiv.png")
            browser.close()
    finally:
        desk.stop()
    assert page_errors == []


def test_user_reads_error_notices_in_english(tmp_path: Path) -> None:
    """TD-I18N-01. Sichtbare Fehler: leerer Titel, Raumname, kaputte Sicherung."""
    home = tmp_path / "desk"
    home.mkdir()
    desk = Desk(home)
    page_errors: list[str] = []
    title = "Keep me"
    bad = tmp_path / "not-a-backup.zip"
    bad.write_bytes(b"this is not a zip")
    try:
        url = desk.start()
        with sync_playwright() as play:
            before = _chrome_pids()
            browser = _launch(play, ["--disable-features=Translate"])
            page = browser.new_page(
                viewport={"width": 1440, "height": 900},
                locale="en-US",
            )
            page.bring_to_front()
            page.on("pageerror", lambda exc: page_errors.append(str(exc)))
            page.goto(url + "/lang/en", wait_until="networkidle")
            page.wait_for_function("() => window.Alpine !== undefined")
            _raise_chrome(before)
            expect(page.locator("html")).to_have_attribute("lang", "en")
            _create_en(page, title)

            button = page.locator("[data-new-thread]")
            field = page.locator("[data-new-title]")
            button.click()
            if not field.is_visible():
                button.evaluate("el => el.click()")
            expect(field).to_be_visible()
            field.fill("   ")
            page.locator("#thread-list").get_by_role(
                "button", name=_sentence("list.create", "en"), exact=True
            ).click()
            _alert(page, _sentence("ui.error", "en"))
            expect(page.locator("h1")).to_have_text(title)
            expect(page.locator(".thread-title")).to_have_count(1)
            _hides(page, "de", "ui.error")

            room = page.locator("[data-room]")
            room.scroll_into_view_if_needed()
            room.locator("[data-room-name]").fill("   ")
            room.locator("[data-room-create]").click()
            _alert(page, _sentence("room.failed", "en"))
            expect(room).to_contain_text(_sentence("room.none", "en"))
            _hides(page, "de", "room.failed")
            _raise_chrome(before, "fenster-fehler.png")
            _shot(page, "22-fehler.png")

            page.get_by_role("link", name=_sentence("data.nav", "en"), exact=True).click()
            expect(page.locator("h1")).to_have_text(_sentence("data.title", "en"))
            page.locator("#backup-file").set_input_files(bad)
            page.locator('input[name="confirm"]').check()
            page.get_by_role(
                "button", name=_sentence("data.restore", "en"), exact=True
            ).click()
            expect(page.get_by_role("alert")).to_have_text(
                _sentence("data.restore_error", "en")
            )
            _hides(page, "de", "data.restore_error")
            expect(page.locator("body")).not_to_contain_text(
                _sentence("data.backup_error", "en")
            )
            _shot(page, "23-sicherung-fehler.png")

            page.get_by_role("link", name=_sentence("nav.threads", "en"), exact=True).click()
            expect(page.locator("h1")).to_have_text(title)
            expect(page.locator(".thread-title").filter(has_text=title)).to_be_visible()
            browser.close()
    finally:
        desk.stop()
    assert page_errors == []
