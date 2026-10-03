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

    def fill(self, css: str, text: str) -> None:
        element = self.find(css)
        self._call("POST", f"/session/{self.session}/element/{element}/clear", {})
        self._call(
            "POST",
            f"/session/{self.session}/element/{element}/value",
            {"text": text},
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


def _session(port: int) -> tuple[str, str]:
    body = {
        "capabilities": {
            "alwaysMatch": {
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
        }
    }
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
        assert version, "Firefox nennt keine Version"
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
        assert version.startswith("149"), version
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
