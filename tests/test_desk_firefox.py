"""Firefox-Abnahme der ersten Schreibtischschritte.

Die normale Suite öffnet Firefox nicht. Ein sichtbarer Lauf setzt
THREADDESK_FIREFOX=1 und spricht das installierte Firefox über geckodriver an.
Playwright startet dieses Firefox nicht: ihm fehlt die Juggler-Schnittstelle.
Ein WebKit-Lauf ist kein Safari und kein Firefox.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

FIREFOX = os.environ.get(
    "THREADDESK_FIREFOX_BIN",
    "/Applications/Firefox.app/Contents/MacOS/firefox",
)
GECKO = os.environ.get("THREADDESK_GECKODRIVER", "/tmp/geckodriver")
HELPER = Path("/tmp/td-raise")
SHOTS = os.environ.get("THREADDESK_SHOTS")
PACE_S = 1.5
ELEMENT = "element-6066-11e4-a52e-4f735466cecf"


def _firefox_version() -> str:
    out = subprocess.check_output([FIREFOX, "--version"], text=True).strip()
    return out.rsplit(" ", 1)[-1]


def _firefox_pids() -> set[int]:
    out = subprocess.check_output(["ps", "-ax", "-o", "pid=,command="], text=True)
    found: set[int] = set()
    for line in out.splitlines():
        if "Firefox.app/Contents/MacOS/firefox" not in line:
            continue
        if "contentproc" in line or "utility" in line or "socket" in line:
            continue
        found.add(int(line.split(None, 1)[0]))
    return found


def _raise(before: set[int], shot: str | None = None) -> None:
    if not HELPER.exists():
        return
    new = sorted(_firefox_pids() - before)
    if not new:
        return
    pid = new[-1]
    subprocess.run([str(HELPER), str(pid), "activate"], check=False)
    front = subprocess.run(
        [str(HELPER), str(pid), "front"], capture_output=True, text=True
    )
    if front.returncode != 0:
        raise AssertionError(f"Firefox ist nicht das vordere Fenster: {front.stdout.strip()}")
    if SHOTS and shot:
        listed = subprocess.run(
            [str(HELPER), str(pid), "windows"], capture_output=True, text=True
        )
        window_id = listed.stdout.split("\t", 1)[0].strip()
        if window_id.isdigit():
            subprocess.run(
                ["screencapture", "-l", window_id, "-o", str(Path(SHOTS) / shot)],
                check=False,
            )


class Gecko:
    """Kurzer WebDriver-Client für ein temporäres Firefox-Profil."""

    def __init__(self, port: int, session: str) -> None:
        self.port = port
        self.session = session

    def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as exc:
            payload = json.loads(exc.read().decode() or "{}")
            value = payload.get("value", payload)
            message = value.get("message", value) if isinstance(value, dict) else value
            raise AssertionError(f"Firefox: {message}") from exc
        value = payload.get("value", payload)
        if isinstance(value, dict) and value.get("error"):
            raise AssertionError(f"Firefox: {value.get('message', value)}")
        return payload

    def url(self, target: str) -> None:
        self._call("POST", f"/session/{self.session}/url", {"url": target})

    def find(self, css: str) -> str:
        deadline = time.monotonic() + 15
        last = "nicht gefunden"
        while time.monotonic() < deadline:
            try:
                payload = self._call(
                    "POST",
                    f"/session/{self.session}/element",
                    {"using": "css selector", "value": css},
                )
                return payload["value"][ELEMENT]
            except AssertionError as exc:
                last = str(exc)
                time.sleep(0.2)
        raise AssertionError(last)

    def click(self, css: str) -> None:
        element = self.find(css)
        self._call("POST", f"/session/{self.session}/element/{element}/click", {})

    def click_xpath(self, xpath: str) -> None:
        payload = self._call(
            "POST",
            f"/session/{self.session}/element",
            {"using": "xpath", "value": xpath},
        )
        element = payload["value"][ELEMENT]
        self._call("POST", f"/session/{self.session}/element/{element}/click", {})

    def fill(self, css: str, text: str) -> None:
        element = self.find(css)
        self._call("POST", f"/session/{self.session}/element/{element}/clear", {})
        self._call(
            "POST",
            f"/session/{self.session}/element/{element}/value",
            {"text": text},
        )

    def set_file(self, css: str, path: str) -> None:
        element = self.find(css)
        self._call(
            "POST",
            f"/session/{self.session}/element/{element}/value",
            {"text": path},
        )

    def text(self, css: str) -> str:
        element = self.find(css)
        payload = self._call("GET", f"/session/{self.session}/element/{element}/text")
        return str(payload["value"])

    def script(self, source: str) -> object:
        payload = self._call(
            "POST",
            f"/session/{self.session}/execute/sync",
            {"script": source, "args": []},
        )
        return payload["value"]

    def rect(self) -> None:
        self._call(
            "POST",
            f"/session/{self.session}/window/rect",
            {"x": 40, "y": 40, "width": 1440, "height": 900},
        )

    def refresh(self) -> None:
        self._call("POST", f"/session/{self.session}/refresh", {})

    def wait_script(self, source: str, expected: str, seconds: float = 15) -> str:
        deadline = time.monotonic() + seconds
        found = ""
        while time.monotonic() < deadline:
            found = str(self.script(source))
            if found == expected:
                return found
            time.sleep(0.2)
        return found


def _driver(port: int) -> subprocess.Popen[bytes]:
    if not Path(GECKO).is_file():
        raise AssertionError(f"geckodriver fehlt: {GECKO}")
    if not Path(FIREFOX).is_file():
        raise AssertionError(f"Firefox fehlt: {FIREFOX}")
    log = open("/tmp/geckodriver-firefox.log", "wb")
    return subprocess.Popen(
        [GECKO, "--host", "127.0.0.1", "--port", str(port)],
        stdout=log,
        stderr=log,
        start_new_session=True,
    )


def _session(port: int, *, accept_prompts: bool = False) -> tuple[str, str]:
    always: dict = {
        "browserName": "firefox",
        "moz:firefoxOptions": {
            "binary": FIREFOX,
            "args": ["-no-remote"],
            "prefs": {
                "browser.shell.checkDefaultBrowser": False,
                "datareporting.policy.dataSubmissionEnabled": False,
            },
        },
    }
    if accept_prompts:
        always["unhandledPromptBehavior"] = "accept"
    body = {"capabilities": {"alwaysMatch": always}}
    deadline = time.monotonic() + 20
    last = ""
    while time.monotonic() < deadline:
        try:
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/session",
                data=json.dumps(body).encode(),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.load(response)
            value = payload["value"]
            browser = value.get("capabilities", {}).get("browserVersion", "")
            return value["sessionId"], str(browser)
        except Exception as exc:  # noqa: BLE001 - geckodriver braucht einen Moment
            last = str(exc)
            time.sleep(0.2)
    raise AssertionError(f"Firefox-Sitzung fehlt: {last}")


def test_user_creates_a_thread_in_firefox(tmp_path: Path) -> None:
    """TD-START-01. Installiertes Firefox legt einen Thread mit Umlauten an."""
    if os.environ.get("THREADDESK_FIREFOX") != "1":
        return
    from test_desk_browser import Desk, _free_port

    home = tmp_path / "desk"
    home.mkdir()
    desk = Desk(home)
    driver = None
    gecko: Gecko | None = None
    try:
        url = desk.start()
        port = _free_port()
        before = _firefox_pids()
        driver = _driver(port)
        session, version = _session(port)
        assert version == _firefox_version(), version
        gecko = Gecko(port, session)
        gecko.rect()
        time.sleep(PACE_S)
        gecko.url(url + "/lang/de")
        deadline = time.monotonic() + 15
        ready = False
        while time.monotonic() < deadline:
            ready = bool(gecko.script(
                "return !!(document.querySelector('.new-thread')"
                " && document.querySelector('.new-thread')._x_dataStack)"
            ))
            if ready:
                break
            time.sleep(0.2)
        assert ready, "Alpine ist nicht bereit"
        assert gecko.script("return document.documentElement.lang") == "de"
        assert "Wähle links einen Thread" in gecko.text("body")
        _raise(before)
        time.sleep(PACE_S)
        gecko.click("[data-new-thread]")
        time.sleep(PACE_S)
        visible = gecko.script(
            "const field = document.querySelector('[data-new-title]');"
            "if (!field) return false;"
            "const box = field.getBoundingClientRect();"
            "return box.width > 0 && box.height > 0;"
        )
        if not visible:
            gecko.script("document.querySelector('[data-new-thread]').click()")
            time.sleep(PACE_S)
        gecko.click("#thread-list button[type=submit]")
        time.sleep(PACE_S)
        assert gecko.script(
            "return document.querySelectorAll('[data-thread-id]').length"
        ) == 0
        gecko.fill("[data-new-title]", "Prüfthread ÄÖÜ")
        time.sleep(PACE_S)
        gecko.click("#thread-list button[type=submit]")
        deadline = time.monotonic() + 15
        title = ""
        while time.monotonic() < deadline:
            title = str(gecko.script(
                "const node = document.querySelector('h1');"
                "return node ? node.textContent.trim() : ''"
            ))
            if title == "Prüfthread ÄÖÜ":
                break
            time.sleep(0.2)
        assert title == "Prüfthread ÄÖÜ"
        # Die Überschrift wird per Schrift in Großbuchstaben gezeigt. Der Satz bleibt „Schranke“.
        gate = str(gecko.script(
            "return document.querySelector('#gate h2').textContent.trim()"
        ))
        assert gate == "Schranke"
        _raise(before, "fenster-firefox.png")
        if SHOTS:
            folder = Path(SHOTS)
            folder.mkdir(parents=True, exist_ok=True)
            payload = gecko._call("GET", f"/session/{gecko.session}/screenshot")
            (folder / "26-firefox.png").write_bytes(base64.b64decode(payload["value"]))
    finally:
        if gecko is not None:
            try:
                gecko._call("DELETE", f"/session/{gecko.session}")
            except Exception:
                pass
        if driver is not None and driver.poll() is None:
            os.killpg(driver.pid, 15)
            try:
                driver.wait(timeout=8)
            except subprocess.TimeoutExpired:
                os.killpg(driver.pid, 9)
                driver.wait(timeout=5)
        desk.stop()


def _ready(gecko: Gecko) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        ready = bool(gecko.script(
            "return !!(document.querySelector('.new-thread')"
            " && document.querySelector('.new-thread')._x_dataStack)"
        ))
        if ready:
            return
        time.sleep(0.2)
    raise AssertionError("Alpine ist nicht bereit")


def _open_new(gecko: Gecko) -> None:
    time.sleep(PACE_S)
    gecko.click("[data-new-thread]")
    time.sleep(PACE_S)
    visible = gecko.script(
        "const field = document.querySelector('[data-new-title]');"
        "if (!field) return false;"
        "const box = field.getBoundingClientRect();"
        "return box.width > 0 && box.height > 0;"
    )
    if not visible:
        gecko.script("document.querySelector('[data-new-thread]').click()")
        time.sleep(PACE_S)


def _page_shot(gecko: Gecko, name: str) -> None:
    if not SHOTS:
        return
    folder = Path(SHOTS)
    folder.mkdir(parents=True, exist_ok=True)
    payload = gecko._call("GET", f"/session/{gecko.session}/screenshot")
    (folder / name).write_bytes(base64.b64decode(payload["value"]))


def _shown(gecko: Gecko, css: str, expected: str, seconds: float = 3) -> str:
    source = (
        "const node = document.querySelector(" + json.dumps(css) + ");"
        "if (!node) return '';"
        "const box = node.getBoundingClientRect();"
        "if (box.width < 1 || box.height < 1) return '';"
        "return node.textContent.trim();"
    )
    return gecko.wait_script(source, expected, seconds=seconds)


def test_user_keeps_a_note_and_snapshot_in_firefox(tmp_path: Path) -> None:
    """TD-NOTE-01, TD-SNAP-01. Notiz und Zwischenstand in installiertem Firefox."""
    if os.environ.get("THREADDESK_FIREFOX") != "1":
        return
    from test_desk_browser import (
        BOARD, DESCRIPTION, LABEL, LATER, NOTE, TITLE, Desk, _free_port,
    )

    home = tmp_path / "desk"
    home.mkdir()
    desk = Desk(home)
    driver = None
    gecko: Gecko | None = None
    try:
        url = desk.start()
        port = _free_port()
        before = _firefox_pids()
        driver = _driver(port)
        session, version = _session(port, accept_prompts=True)
        assert version == _firefox_version(), version
        gecko = Gecko(port, session)
        gecko.rect()
        time.sleep(PACE_S)
        gecko.url(url + "/lang/de")
        _ready(gecko)
        _raise(before)
        _open_new(gecko)
        gecko.fill("[data-new-title]", TITLE)
        gecko.fill('#thread-list input[name="description"]', DESCRIPTION)
        time.sleep(PACE_S)
        gecko.click("#thread-list button[type=submit]")
        assert gecko.wait_script(
            "return document.body.innerText.includes("
            + json.dumps(f"Angelegt: {TITLE}")
            + ") ? 'angelegt' : ''",
            "angelegt",
            seconds=8,
        ) == "angelegt"
        assert gecko.wait_script(
            "const node = document.querySelector('h1');"
            "return node ? node.textContent.trim() : ''",
            TITLE,
        ) == TITLE
        assert gecko.script(
            "const field = document.querySelector('.desk-description input[name=\"text\"]');"
            "return field ? field.value : ''"
        ) == DESCRIPTION

        time.sleep(PACE_S)
        gecko.fill('#notes textarea[name="text"]', NOTE)
        time.sleep(PACE_S)
        gecko.click_xpath("//section[@id='notes']//button[normalize-space()='Notiz speichern']")
        assert gecko.wait_script(
            "return document.body.innerText.includes('Notiz gespeichert') ? 'notiz' : ''",
            "notiz",
            seconds=5,
        ) == "notiz"
        assert gecko.script(
            "return document.querySelector('#notes textarea[name=\"text\"]').value"
        ) == NOTE

        time.sleep(PACE_S)
        gecko.refresh()
        _ready(gecko)
        assert gecko.script(
            "const node = document.querySelector('h1');"
            "return node ? node.textContent.trim() : ''"
        ) == TITLE
        assert gecko.script(
            "return document.querySelector('#notes textarea[name=\"text\"]').value"
        ) == NOTE

        time.sleep(PACE_S)
        gecko.script("document.querySelector('[data-whiteboard-content]').scrollIntoView({block:'center'})")
        gecko.fill("[data-whiteboard-content]", BOARD)
        time.sleep(PACE_S)
        gecko.click("[data-whiteboard-submit]")
        assert gecko.wait_script(
            "const node = document.querySelector('.whiteboard-body');"
            "return node ? node.textContent.trim() : ''",
            BOARD,
        ) == BOARD

        time.sleep(PACE_S)
        gecko.script("document.querySelector('#snapshots').scrollIntoView({block:'center'})")
        gecko.fill("[data-snapshot-label]", LABEL)
        time.sleep(PACE_S)
        gecko.click("#snapshots form.inline-form button[type=submit]")
        assert gecko.wait_script(
            "const node = document.querySelector('.snap-label');"
            "return node ? node.textContent.trim() : ''",
            LABEL,
        ) == LABEL

        time.sleep(PACE_S)
        gecko.fill('#notes textarea[name="text"]', LATER)
        time.sleep(PACE_S)
        gecko.click_xpath("//section[@id='notes']//button[normalize-space()='Notiz speichern']")
        assert gecko.wait_script(
            "return document.querySelector('#notes textarea[name=\"text\"]').value",
            LATER,
        ) == LATER

        time.sleep(PACE_S)
        gecko.script("document.querySelector('#snapshots').scrollIntoView({block:'center'})")
        gecko.click("#snapshots .snap-item button[type=submit]")
        assert gecko.wait_script(
            "return document.querySelector('#notes textarea[name=\"text\"]').value",
            NOTE,
        ) == NOTE
        assert gecko.script(
            "return document.querySelector('.whiteboard-body').textContent.trim()"
        ) == BOARD
        assert gecko.script(
            "return document.querySelector('.snap-label').textContent.trim()"
        ) == LABEL
        assert LATER not in str(gecko.script("return document.body.textContent"))
        _raise(before, "fenster-firefox-zwischenstand.png")
        _page_shot(gecko, "27-firefox-zwischenstand.png")

        gecko._call("DELETE", f"/session/{gecko.session}")
        gecko = None
        desk.stop()
        url = desk.start()
        before = _firefox_pids()
        session, version = _session(port, accept_prompts=True)
        gecko = Gecko(port, session)
        gecko.rect()
        time.sleep(PACE_S)
        gecko.url(url + "/")
        _ready(gecko)
        assert gecko.script(
            "const node = document.querySelector('.thread-title');"
            "return node ? node.textContent.trim() : ''"
        ) == TITLE
        assert gecko.script(
            "return document.querySelector('#notes textarea[name=\"text\"]').value"
        ) == NOTE
        assert gecko.script(
            "return document.querySelector('.whiteboard-body').textContent.trim()"
        ) == BOARD
        assert LATER not in str(gecko.script("return document.body.textContent"))
        _raise(before, "fenster-firefox-neustart.png")
        _page_shot(gecko, "28-firefox-neustart.png")
    finally:
        if gecko is not None:
            try:
                gecko._call("DELETE", f"/session/{gecko.session}")
            except Exception:
                pass
        if driver is not None and driver.poll() is None:
            os.killpg(driver.pid, 15)
            try:
                driver.wait(timeout=8)
            except subprocess.TimeoutExpired:
                os.killpg(driver.pid, 9)
                driver.wait(timeout=5)
        desk.stop()


def test_user_reads_error_notices_in_firefox(tmp_path: Path) -> None:
    """TD-I18N-01. Deutsche Fehlersätze: leerer Titel, Raumname, kaputte Sicherung."""
    if os.environ.get("THREADDESK_FIREFOX") != "1":
        return
    from test_desk_browser import Desk, _free_port
    from threaddesk.core import i18n

    kept = "Behalten"
    ui_error = i18n.translate("ui.error", "de")
    room_failed = i18n.translate("room.failed", "de")
    room_none = i18n.translate("room.none", "de")
    restore_error = i18n.translate("data.restore_error", "de")
    backup_error = i18n.translate("data.backup_error", "de")
    data_title = i18n.translate("data.title", "de")
    bad = tmp_path / "unbrauchbar.zip"
    bad.write_bytes(b"this is not a zip")
    home = tmp_path / "desk"
    home.mkdir()
    desk = Desk(home)
    driver = None
    gecko: Gecko | None = None
    try:
        url = desk.start()
        port = _free_port()
        before = _firefox_pids()
        driver = _driver(port)
        session, version = _session(port)
        assert version == _firefox_version(), version
        gecko = Gecko(port, session)
        gecko.rect()
        time.sleep(PACE_S)
        gecko.url(url + "/lang/de")
        _ready(gecko)
        assert gecko.script("return document.documentElement.lang") == "de"
        _raise(before)
        _open_new(gecko)
        gecko.fill("[data-new-title]", kept)
        time.sleep(PACE_S)
        gecko.click("#thread-list button[type=submit]")
        assert gecko.wait_script(
            "const node = document.querySelector('h1');"
            "return node ? node.textContent.trim() : ''",
            kept,
        ) == kept

        time.sleep(PACE_S)
        _open_new(gecko)
        gecko.fill("[data-new-title]", "   ")
        time.sleep(PACE_S)
        gecko.click("#thread-list button[type=submit]")
        assert _shown(gecko, ".toast-stack .banner-error", ui_error) == ui_error
        assert i18n.translate("ui.error", "en") not in str(
            gecko.script("return document.body.textContent")
        )
        assert gecko.script(
            "const node = document.querySelector('h1');"
            "return node ? node.textContent.trim() : ''"
        ) == kept
        assert gecko.script(
            "return document.querySelectorAll('[data-thread-id]').length"
        ) == 1
        _raise(before, "fenster-firefox-titel-fehler.png")
        _page_shot(gecko, "29-firefox-titel-fehler.png")

        time.sleep(PACE_S)
        gecko.script(
            "document.querySelector('[data-room]').scrollIntoView({block:'center'})"
        )
        gecko.fill("[data-room-name]", "   ")
        time.sleep(PACE_S)
        gecko.click("[data-room-create]")
        assert _shown(gecko, ".toast-stack .banner-error", room_failed) == room_failed
        assert room_none in str(gecko.script(
            "const node = document.querySelector('[data-room]');"
            "return node ? node.textContent : ''"
        ))
        assert gecko.script("return document.querySelector('[data-room-current]')") is None
        assert i18n.translate("room.failed", "en") not in str(
            gecko.script("return document.body.textContent")
        )
        _raise(before, "fenster-firefox-raum-fehler.png")
        _page_shot(gecko, "30-firefox-raum-fehler.png")

        time.sleep(PACE_S)
        gecko.click('a[href="/data"]')
        assert gecko.wait_script(
            "const node = document.querySelector('h1');"
            "return node ? node.textContent.trim() : ''",
            data_title,
            seconds=15,
        ) == data_title
        assert gecko.script("return document.documentElement.lang") == "de"
        gecko.script("document.querySelector('#backup-file').scrollIntoView({block:'center'})")
        time.sleep(PACE_S)
        gecko.set_file("#backup-file", str(bad))
        chosen = gecko.script(
            "const input = document.querySelector('#backup-file');"
            "return input && input.files && input.files.length"
            " ? input.files[0].name : ''"
        )
        assert chosen == bad.name, chosen
        gecko.click('input[name="confirm"]')
        assert gecko.script(
            "return document.querySelector('input[name=\"confirm\"]').checked"
        ) is True
        time.sleep(PACE_S)
        gecko.click_xpath("//form[@action='/data/restore']//button[@type='submit']")
        assert _shown(gecko, "p[role=alert]", restore_error, seconds=15) == restore_error
        body = str(gecko.script("return document.body.textContent"))
        assert i18n.translate("data.restore_error", "en") not in body
        assert backup_error not in body
        assert gecko.script(
            "const node = document.querySelector('h1');"
            "return node ? node.textContent.trim() : ''"
        ) == data_title
        _raise(before, "fenster-firefox-sicherung-fehler.png")
        _page_shot(gecko, "31-firefox-sicherung-fehler.png")

        time.sleep(PACE_S)
        gecko.click('a[href="/"]')
        assert gecko.wait_script(
            "const node = document.querySelector('h1');"
            "return node ? node.textContent.trim() : ''",
            kept,
        ) == kept
        assert gecko.script(
            "return document.querySelectorAll('[data-thread-id]').length"
        ) == 1
    finally:
        if gecko is not None:
            try:
                gecko._call("DELETE", f"/session/{gecko.session}")
            except Exception:
                pass
        if driver is not None and driver.poll() is None:
            os.killpg(driver.pid, 15)
            try:
                driver.wait(timeout=8)
            except subprocess.TimeoutExpired:
                os.killpg(driver.pid, 9)
                driver.wait(timeout=5)
        desk.stop()
