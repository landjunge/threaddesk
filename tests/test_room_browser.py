"""Real clicks, two real processes, and synthetic data for both storage engines."""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

import pytest

pytest.importorskip("playwright.sync_api", reason="browser extra not installed")
from playwright.sync_api import expect, sync_playwright

from threaddesk.core.models import WhiteboardEntry
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore

ROOT = Path(__file__).resolve().parents[1]
HEADED = os.environ.get("THREADDESK_BROWSER_HEADED") == "1"
SHOTS = os.environ.get("THREADDESK_SHOTS")
# Sichtbares Fenster: jede Aktion wartet 1,5 Sekunden. Kopflos bleibt schnell.
PACE_MS = 1500


class Desk:
    def __init__(self, home: Path, storage: str):
        self.home, self.storage = home, storage
        self.home.mkdir()
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self.proc = None
        self.log = home.parent / f"{home.name}.log"

    def start(self):
        env = os.environ.copy()
        env.update(THREADDESK_HOME=str(self.home), THREADDESK_STORAGE=self.storage,
                   THREADDESK_LANG="de", NO_PROXY="127.0.0.1,localhost",
                   PYTHONPATH=str(ROOT / "src"))
        with self.log.open("a", encoding="utf-8") as output:
            self.proc = subprocess.Popen(
                [sys.executable, "-m", "threaddesk.ui.cli", "serve", "--host", "127.0.0.1",
                 "--port", str(self.port)], cwd=ROOT, env=env, stdout=output, stderr=subprocess.STDOUT,
            )
        deadline = time.monotonic() + 25
        opener = build_opener(ProxyHandler({}))
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(self.log.read_text(encoding="utf-8"))
            try:
                with opener.open(self.url + "/", timeout=0.5) as response:
                    if response.status == 200:
                        return
            except (OSError, URLError):
                pass
            time.sleep(0.05)
        raise RuntimeError("Isolated test server did not become ready: " + self.log.read_text(encoding="utf-8"))

    def stop(self):
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=8)
        self.proc = None

    def store(self):
        return (SQLiteStore if self.storage == "sqlite" else JsonStore)(self.home)


@contextmanager
def running(desk):
    try:
        desk.start()
        yield desk
    finally:
        desk.stop()


def _chrome_pids() -> set[int]:
    out = subprocess.check_output(["ps", "-ax", "-o", "pid=,command="], text=True)
    found: set[int] = set()
    for line in out.splitlines():
        if "Google Chrome.app/Contents/MacOS/Google Chrome" in line and "Helper" not in line:
            found.add(int(line.split(None, 1)[0]))
    return found


def _raise_chrome(before: set[int], shot: str | None = None) -> None:
    helper = Path("/tmp/td-raise")
    if not HEADED or not helper.exists():
        return
    new = sorted(_chrome_pids() - before)
    if not new:
        return
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


def click_post(page, selector, path):
    with page.expect_response(lambda response: response.request.method == "POST"
                              and response.url.split("?", 1)[0].endswith(path)) as result:
        page.locator(selector).click()
    assert result.value.ok, f"{path}: HTTP {result.value.status}"
    expect(page.locator("#workspace.htmx-swapping")).to_have_count(0)
    expect(page.locator(".htmx-request")).to_have_count(0)


def create_thread(page, title):
    page.locator("[data-new-thread]").click()
    page.locator("[data-new-title]").fill(title)
    click_post(page, '.new-thread form button[type="submit"]', "/threads")
    expect(page.locator(".detail h1")).to_have_text(title)
    return page.locator(".thread-item.is-current").get_attribute("data-thread-id")


def select_thread(page, thread_id):
    click_post(page, f'[data-thread-id="{thread_id}"]', f"/threads/{thread_id}/switch")
    expect(page.locator(".thread-item.is-current")).to_have_attribute("data-thread-id", thread_id)


def add_entry(page, thread_id, text, shared):
    page.locator("[data-whiteboard-content]").fill(text)
    share = page.locator("[data-room-share]")
    if shared:
        share.check()
    elif share.is_checked():
        share.uncheck()
    click_post(page, "[data-whiteboard-submit]", f"/threads/{thread_id}/whiteboard")
    expect(page.locator(".whiteboard-body").filter(has_text=text)).to_have_count(1)


def synchronize(page):
    click_post(page, "[data-room-sync]", "/rooms/sync")


def pair_via_ui(a, b, a_url, name, role):
    a.locator("[data-room-name]").fill(name)
    click_post(a, "[data-room-create]", "/rooms")
    expect(a.locator("[data-room-current]")).to_have_text(name)
    a.locator("[data-room-invite-role]").select_option(role)
    click_post(a, "[data-room-invite]", "/rooms/invite")
    code = a.locator("[data-room-code]").inner_text().split()[-1]
    b.locator("[data-room-join-code]").fill(code)
    b.locator("[data-room-peer]").fill(a_url)
    click_post(b, "[data-room-join]", "/rooms/join")
    expect(b.locator("[data-room-current]")).to_have_text(name)
    expect(b.locator("[data-room-members] li")).to_have_count(2)
    return a.locator("[data-room-select]").input_value()


@pytest.mark.parametrize("storage", ["json", "sqlite"])
def test_team_room_real_browser(tmp_path, storage):
    left, right = Desk(tmp_path / "left", storage), Desk(tmp_path / "right", storage)
    assert left.home != right.home and left.port != right.port
    with sync_playwright() as play, ExitStack() as stack:
        stack.enter_context(running(left))
        stack.enter_context(running(right))
        with ExitStack() as browser_stack:
            before = _chrome_pids()
            browser = play.chromium.launch(
                executable_path=os.environ.get("THREADDESK_CHROMIUM") or None,
                headless=not HEADED,
                slow_mo=PACE_MS if HEADED else 0,
                args=["--start-fullscreen"] if HEADED else [],
            )
            browser_stack.callback(browser.close)
            context_a = browser.new_context(locale="de-DE", viewport={"width": 1440, "height": 1000})
            context_b = browser.new_context(locale="de-DE", viewport={"width": 1440, "height": 1000})
            external = []
            def local_only(route):
                from urllib.parse import urlparse
                if urlparse(route.request.url).hostname != "127.0.0.1":
                    external.append(route.request.url)
                    route.abort()
                else:
                    route.continue_()
            context_a.route("**/*", local_only)
            context_b.route("**/*", local_only)
            a, b = context_a.new_page(), context_b.new_page()
            a.goto(left.url)
            b.goto(right.url)
            a.bring_to_front()
            _raise_chrome(before)
            instance_a = a.locator("[data-room-instance]").inner_text().split()[-1]
            instance_b = b.locator("[data-room-instance]").inner_text().split()[-1]
            assert instance_a != instance_b
            room = pair_via_ui(a, b, left.url, "Browser Werkstatt", "member")
            a.reload()
            expect(a.locator("[data-room-members] li")).to_have_count(2)
            thread_a = create_thread(a, "Browser A")
            thread_b = create_thread(b, "Browser B")
            note_form = a.locator(f'form[hx-post="/threads/{thread_a}/note"]')
            note_form.locator('textarea[name="text"]').fill("PRIVAT-NOTIZ-NICHT-TEILEN")
            click_post(a, f'form[hx-post="/threads/{thread_a}/note"] button[type="submit"]',
                       f"/threads/{thread_a}/note")
            add_entry(a, thread_a, "PRIVAT-WHITEBOARD-NICHT-TEILEN", False)
            add_entry(a, thread_a, "Gemeinsam von A", True)
            synchronize(b)
            select_thread(b, thread_a)
            expect(b.locator(".whiteboard-body").filter(has_text="Gemeinsam von A")).to_have_count(1)
            expect(b.locator("body")).not_to_contain_text("PRIVAT-WHITEBOARD-NICHT-TEILEN")
            expect(b.locator(f'form[hx-post="/threads/{thread_a}/note"] textarea')).to_have_value("")
            select_thread(b, thread_b)
            add_entry(b, thread_b, "Gemeinsam von B", True)
            synchronize(a)
            select_thread(a, thread_b)
            expect(a.locator(".whiteboard-body").filter(has_text="Gemeinsam von B")).to_have_count(1)

            right.stop()
            select_thread(a, thread_a)
            add_entry(a, thread_a, "Nach der Unterbrechung", True)
            synchronize(a)
            expect(a.locator("[data-room-state]")).to_have_attribute("data-room-state", "peer_down")
            expect(a.locator("[data-room-state]")).to_have_text("Gegenstelle nicht erreichbar")
            right.start()
            b.reload()
            synchronize(a)
            b.reload()
            select_thread(b, thread_a)
            expect(b.locator(".whiteboard-body").filter(has_text="Nach der Unterbrechung")).to_have_count(1)

            # There is no edit route in the append-only board. Only the stopped
            # synthetic stores prepare this collision; synchronization uses clicks.
            left.stop()
            right.stop()
            for desk, instance, text in ((left, instance_a, "Browser Fassung A"),
                                         (right, instance_b, "Browser Fassung B")):
                desk.store().append_whiteboard_entry(WhiteboardEntry(
                    id="browser-conflict", thread_id=thread_a, actor="Synthetic tester",
                    actor_type="human", created_at="2026-10-02T00:00:00+00:00", entry_type="note",
                    content=text, room_id=room, instance_id=instance,
                ))
            left.start()
            right.start()
            a.reload()
            b.reload()
            synchronize(a)
            expect(a.locator("[data-room-state]")).to_have_attribute("data-room-state", "conflict_kept")
            synchronize(b)
            select_thread(a, thread_a)
            select_thread(b, thread_a)
            for page in (a, b):
                expect(page.locator("[data-whiteboard-log]")).to_contain_text("Browser Fassung A")
                expect(page.locator("[data-whiteboard-log]")).to_contain_text("Browser Fassung B")
            synchronize(a)
            synchronize(b)
            counts = [len(desk.store().list_whiteboard(thread_a)) for desk in (left, right)]
            for _ in range(3):
                synchronize(a)
                synchronize(b)
            assert counts == [len(desk.store().list_whiteboard(thread_a)) for desk in (left, right)]

            pair_via_ui(a, b, left.url, "Browser Leseraum", "read_only")
            expect(b.locator("[data-room-members]")).to_contain_text("Nur lesen")
            add_entry(a, thread_a, "Nur lesen von A", True)
            synchronize(b)
            expect(b.locator("[data-whiteboard-log]")).to_contain_text("Nur lesen von A")
            expect(b.locator("[data-room-share]")).to_be_disabled()
            rejected = b.request.post(right.url + f"/threads/{thread_a}/whiteboard", form={
                "actor": "Synthetic reader", "actor_type": "human", "entry_type": "note",
                "content": "Verbotene Freigabe", "in_room": "1",
            })
            assert rejected.status == 403
            add_entry(b, thread_a, "Leser darf nicht senden", False)
            synchronize(a)
            synchronize(b)
            assert "Leser darf nicht senden" not in [entry.content for entry in left.store().list_whiteboard(thread_a)]

            left.stop()
            right.stop()
            left.start()
            right.start()
            a.reload()
            b.reload()
            assert a.locator("[data-room-instance]").inner_text().split()[-1] == instance_a
            assert b.locator("[data-room-instance]").inner_text().split()[-1] == instance_b
            synchronize(a)
            expect(a.locator("[data-room-state]")).to_have_attribute("data-room-state", "synced")
            assert external == [], "The local UI must not request a CDN or another external host"
            assert left.store().get_thread(thread_a).context.notes == "PRIVAT-NOTIZ-NICHT-TEILEN"
            assert right.store().get_thread(thread_a).context.notes == ""
            assert "PRIVAT-WHITEBOARD-NICHT-TEILEN" not in [entry.content for entry in right.store().list_whiteboard(thread_a)]


def _sentence(key: str, language: str, **values: object) -> str:
    from threaddesk.core import i18n

    return i18n.translate(key, language, **values)


def _state(page, name: str) -> None:
    chip = page.locator("[data-room-state]")
    expect(chip).to_have_attribute("data-room-state", name)
    expect(chip).to_have_text(_sentence(f"room.state.{name}", "en"))


def _toast(page, text: str) -> None:
    banner = page.locator(".toast-stack .banner-ok")
    expect(banner).to_be_visible()
    expect(banner).to_have_text(text)


def _english(page, url: str) -> None:
    page.goto(url + "/lang/en", wait_until="networkidle")
    page.wait_for_function("() => window.Alpine !== undefined")
    expect(page.locator("html")).to_have_attribute("lang", "en")


def test_user_reads_room_states_in_english(tmp_path) -> None:
    """TD-I18N-01. Die sechs Raumzustände und die Rollenworte auf Englisch."""
    left, right = Desk(tmp_path / "left", "json"), Desk(tmp_path / "right", "json")
    page_errors: list[str] = []
    with sync_playwright() as play, ExitStack() as stack:
        stack.enter_context(running(left))
        stack.enter_context(running(right))
        with ExitStack() as browser_stack:
            before = _chrome_pids()
            browser = play.chromium.launch(
                executable_path=os.environ.get("THREADDESK_CHROMIUM") or None,
                headless=not HEADED,
                slow_mo=PACE_MS if HEADED else 0,
                args=["--disable-features=Translate", *(["--start-fullscreen"] if HEADED else [])],
            )
            browser_stack.callback(browser.close)
            context_a = browser.new_context(locale="en-US", viewport={"width": 1440, "height": 1000})
            context_b = browser.new_context(locale="en-US", viewport={"width": 1440, "height": 1000})
            external = []

            def local_only(route):
                from urllib.parse import urlparse
                if urlparse(route.request.url).hostname != "127.0.0.1":
                    external.append(route.request.url)
                    route.abort()
                else:
                    route.continue_()

            context_a.route("**/*", local_only)
            context_b.route("**/*", local_only)
            a, b = context_a.new_page(), context_b.new_page()
            for page in (a, b):
                page.on("pageerror", lambda exc: page_errors.append(str(exc)))
            _english(a, left.url)
            _english(b, right.url)
            a.bring_to_front()
            _raise_chrome(before)
            instance_a = a.locator("[data-room-instance]").inner_text().split()[-1]
            instance_b = b.locator("[data-room-instance]").inner_text().split()[-1]
            assert instance_a != instance_b
            for page in (a, b):
                _state(page, "not_connected")
                expect(page.locator("[data-room]")).to_contain_text(_sentence("room.none", "en"))
                expect(page.locator("body")).not_to_contain_text(
                    _sentence("room.state.not_connected", "de")
                )
                expect(page.locator("body")).not_to_contain_text(_sentence("room.none", "de"))

            a.locator("[data-room-name]").fill("English room")
            click_post(a, "[data-room-create]", "/rooms")
            _toast(a, _sentence("room.created", "en"))
            expect(a.locator("[data-room-current]")).to_have_text("English room")
            expect(a.locator("[data-room-members]")).to_contain_text(
                _sentence("room.role.owner", "en")
            )
            expect(a.locator("[data-room]")).to_contain_text(_sentence("room.never", "en"))
            expect(a.locator("body")).not_to_contain_text(_sentence("room.created", "de"))
            expect(a.locator("body")).not_to_contain_text(_sentence("room.role.owner", "de"))
            _state(a, "not_connected")
            room = a.locator("[data-room-select]").input_value()

            a.locator("[data-room-invite-role]").select_option("member")
            click_post(a, "[data-room-invite]", "/rooms/invite")
            code = a.locator("[data-room-code]").inner_text().split()[-1]
            _toast(a, _sentence("room.invited", "en", code=code))
            expect(a.locator("body")).not_to_contain_text("Einladungscode:")

            b.locator("[data-room-join-code]").fill(code)
            b.locator("[data-room-peer]").fill(left.url)
            click_post(b, "[data-room-join]", "/rooms/join")
            _toast(b, _sentence("room.paired", "en"))
            _state(b, "connected")
            expect(b.locator("[data-room-members]")).to_contain_text(
                _sentence("room.role.member", "en")
            )
            expect(b.locator("body")).not_to_contain_text(_sentence("room.paired", "de"))
            expect(b.locator("body")).not_to_contain_text(_sentence("room.state.connected", "de"))

            a.reload(wait_until="networkidle")
            _state(a, "connected")
            expect(a.locator("[data-room-members]")).to_contain_text(
                _sentence("room.role.member", "en")
            )

            thread_a = create_thread(a, "English thread")
            add_entry(a, thread_a, "Shared line", True)
            synchronize(a)
            _toast(a, _sentence("room.state.synced", "en"))
            _state(a, "synced")
            expect(a.locator("body")).not_to_contain_text(_sentence("room.state.synced", "de"))

            add_entry(a, thread_a, "A later shared line", True)
            _state(a, "changes")
            expect(a.locator("body")).not_to_contain_text(_sentence("room.state.changes", "de"))

            right.stop()
            synchronize(a)
            _toast(a, _sentence("room.state.peer_down", "en"))
            _state(a, "peer_down")
            expect(a.locator("body")).not_to_contain_text(
                _sentence("room.state.peer_down", "de")
            )
            if SHOTS:
                Path(SHOTS).mkdir(parents=True, exist_ok=True)
                a.screenshot(path=str(Path(SHOTS) / "18-raum.png"), full_page=True)
            _raise_chrome(before, "fenster-raum.png")

            left.stop()
            for desk, instance, text in (
                (left, instance_a, "English copy A"),
                (right, instance_b, "English copy B"),
            ):
                desk.store().append_whiteboard_entry(WhiteboardEntry(
                    id="english-room-conflict", thread_id=thread_a, actor="Synthetic tester",
                    actor_type="human", created_at="2026-10-03T00:00:00+00:00", entry_type="note",
                    content=text, room_id=room, instance_id=instance,
                ))
            left.start()
            right.start()
            a.reload(wait_until="networkidle")
            b.reload(wait_until="networkidle")
            synchronize(a)
            _toast(a, _sentence("room.state.conflict_kept", "en"))
            _state(a, "conflict_kept")
            expect(a.locator("body")).not_to_contain_text(
                _sentence("room.state.conflict_kept", "de")
            )
            synchronize(b)
            select_thread(a, thread_a)
            select_thread(b, thread_a)
            for page in (a, b):
                expect(page.locator("[data-whiteboard-log]")).to_contain_text("English copy A")
                expect(page.locator("[data-whiteboard-log]")).to_contain_text("English copy B")

            pair_via_ui(a, b, left.url, "English reading room", "read_only")
            expect(b.locator("[data-room-members]")).to_contain_text(
                _sentence("room.role.read_only", "en")
            )
            expect(b.locator("body")).not_to_contain_text(_sentence("room.role.read_only", "de"))
            select_thread(b, thread_a)
            expect(b.locator("[data-room-share]")).to_be_disabled()
            expect(b.locator("[data-whiteboard]")).to_contain_text(
                _sentence("room.local_only", "en")
            )
            assert external == [], "The local UI must not request a CDN or another external host"
    assert page_errors == []
