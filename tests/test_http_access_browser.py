"""Synthetic homes, reserved ports and temporary headless browser profiles only."""
import html
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import expect, sync_playwright
import uvicorn
import pytest
import threaddesk.ui.server as ui
from threaddesk.storage.sqlite_store import SQLiteStore

from threaddesk.api.service import ThreadService
from threaddesk.services.hausmeister import MODEL_STATUS_TTL_SECONDS
from threaddesk.storage.json_store import JsonStore
from threaddesk.ui.server import create_app


@pytest.mark.parametrize("backend", ["json", "sqlite"])
def test_real_browser_can_save_and_download_but_foreign_form_cannot_write(tmp_path, monkeypatch, backend):
    home = tmp_path / "synthetic-home"
    monkeypatch.setenv("THREADDESK_HOME", str(home))
    monkeypatch.setenv("THREADDESK_STORAGE", backend)
    probes = []
    monkeypatch.setattr("threaddesk.services.hausmeister.list_models", lambda *a, **kw: probes.append(True) or [])
    svc = ThreadService((SQLiteStore if backend == "sqlite" else JsonStore)(home))
    thread = svc.create("CSRF browser acceptance")
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = listener.getsockname()[1]
    assert port not in {8765, 8766, 8767}
    url = f"http://127.0.0.1:{port}"
    app = create_app()
    server = uvicorn.Server(uvicorn.Config(app, log_config=None, log_level="error", proxy_headers=False))
    worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    worker.start()
    attacker = None
    attacker_worker = None
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.05)
        assert server.started
        registry_files = [svc.store.artifact_path(name) for name in ["actors.json", "modules.json"]]
        startup_registries = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in registry_files}
        with sync_playwright() as play:
            browser = play.chromium.launch(channel="chrome", headless=True)
            try:
                context = browser.new_context(accept_downloads=True, locale="en-US")
                page = context.new_page()
                page.goto(url + "/?lang=de")
                expect(page.locator("html")).to_have_attribute("lang", "de")
                expect(page.locator(".preferences > summary")).to_contain_text("DE")
                assert startup_registries == {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in registry_files}
                token = page.locator('meta[name="threaddesk-csrf"]').get_attribute("content")
                disclosure = page.locator('details[data-disclosure="notes"]')
                disclosure.locator("summary").click()
                note = disclosure.locator('textarea[name="text"]')
                note.fill("legitimate HTMX note")
                note_url = url + f"/threads/{thread.id}/note"
                with page.expect_response(lambda response: response.url == note_url
                                          and response.request.method == "POST") as saved_note:
                    disclosure.locator('button[type="submit"]').click()
                response = saved_note.value
                assert response.status == 200, response.text()
                response.finished()
                assert response.request.headers["x-threaddesk-view-language"] == "de"
                expect(page.locator("#workspace .banner-ok")).to_have_text("Notiz gespeichert")
                expect(page.locator(".preferences > summary")).to_contain_text("DE")
                expect(page.locator('#notes textarea[name="text"]')).to_have_value("legitimate HTMX note")
                assert svc.get(thread.id).context.notes == "legitimate HTMX note"
                # The same explicit view context also accompanies fetch callers.
                fetched = page.evaluate("""async (path) => {
                    const data = new FormData(); data.set('text', 'legitimate HTMX note');
                    const response = await window.threadDeskWrite(path, {body: data});
                    return {status: response.status, text: await response.text()};
                }""", f"/threads/{thread.id}/note")
                assert fetched["status"] == 200 and "Notiz gespeichert" in fetched["text"]
                assert svc.get(thread.id).context.notes == "legitimate HTMX note"
                # Actual protected preference POSTs override the old document's
                # locale, including its stale Referer and transported query.
                for code in ("en", "de"):
                    if page.locator(".preferences").get_attribute("open") is None:
                        page.locator(".preferences > summary").click()
                    with page.expect_navigation(wait_until="domcontentloaded"):
                        page.locator(f'form[action^="/lang/{code}"] button').click()
                    expect(page.locator("html")).to_have_attribute("lang", code)
                    expect(page.locator(".preferences > summary")).to_contain_text(code.upper())
                for mode in ("expert", "plain"):
                    if page.locator(".preferences").get_attribute("open") is None:
                        page.locator(".preferences > summary").click()
                    with page.expect_navigation(wait_until="domcontentloaded"):
                        page.locator(f'form[action^="/mode/{mode}"] button').click()
                    expect(page.locator("body")).to_have_attribute("data-register", mode)
                    expect(page.locator("html")).to_have_attribute("lang", "de")
                page.get_by_role("link", name="Daten", exact=True).click()
                with page.expect_download() as download:
                    page.get_by_role("button", name="Sicherung herunterladen", exact=True).click()
                saved = tmp_path / "synthetic-backup.zip"
                download.value.save_as(saved)
                assert parse_qs(urlsplit(download.value.url).query) == {"lang": ["de"], "mode": ["plain"]}
                assert saved.stat().st_size > 0
                assert svc.get(thread.id).context.notes == "legitimate HTMX note"
                svc.set_note("original changed after backup", thread.id)
                page.locator("#backup-file").set_input_files(saved)
                page.locator("input[name=confirm]").check()
                page.get_by_role("button", name="Sicherung öffnen", exact=True).click()
                page.wait_for_url(url + "/?restored=1")
                assert svc.get(thread.id).context.notes == "original changed after backup"
                svc = ui._svc()  # Read the actually selected isolated restored profile.
                assert svc.get(thread.id).context.notes == "legitimate HTMX note"
                restored_files = [svc.store.artifact_path(name) for name in ["actors.json", "modules.json"]]
                restored_registries = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in restored_files}

                # A different port is a different Origin even though SameSite may match.
                # Give the fixture a known CSRF token deliberately: Origin must still deny it.
                target = url + f"/threads/{thread.id}/note"
                attack_html = ('<form method="post" action="' + html.escape(target, quote=True) + '">'
                               '<input name="text" value="FORGED"><input name="csrf_token" value="'
                               + html.escape(token, quote=True) + '"><button>Attack</button></form>'
                               + '<a href="' + url + '/">Open local workspace</a>').encode()

                class AttackPage(BaseHTTPRequestHandler):
                    def do_GET(self):
                        self.send_response(200)
                        self.send_header("Content-Type", "text/html")
                        self.end_headers()
                        self.wfile.write(attack_html)

                    def log_message(self, *_):
                        pass

                attacker = ThreadingHTTPServer(("127.0.0.1", 0), AttackPage)
                assert attacker.server_port not in {8765, 8766, 8767}
                attacker_worker = threading.Thread(target=attacker.serve_forever, daemon=True)
                attacker_worker.start()
                page.goto(f"http://127.0.0.1:{attacker.server_port}/")
                with page.expect_response(lambda response: response.url == target and response.request.method == "POST") as denied:
                    page.get_by_role("button", name="Attack").click()
                assert denied.value.status == 403
                assert denied.value.json()["error"] == "foreign_origin"
                assert svc.get(thread.id).context.notes == "legitimate HTMX note"
                assert len(svc.list(True)) == 1
                # Ordinary incoming navigation must not invalidate an already open editor's token.
                page.goto(f"http://localhost:{attacker.server_port}/")
                page.get_by_role("link", name="Open local workspace").click()
                page.wait_for_url(url + "/")
                assert page.locator('meta[name="threaddesk-csrf"]').get_attribute("content") == token
                assert restored_registries == {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in restored_files}
                assert startup_registries == {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in registry_files}
                # Expiration also updates an already open page, without any request/probe.
                svc.store.write_json_artifact("hausmeister.json", {"version": 1, "model": "saved-synthetic"})
                key = str(svc.store.artifact_path("hausmeister.json"))
                app.state.hausmeister_probes[key]["observed_monotonic"] = time.monotonic() - MODEL_STATUS_TTL_SECONDS + 2
                before_expiry = len(probes)
                page.reload()
                section = page.locator("[data-hausmeister]")
                expect(section).to_have_attribute("data-ollama", "up")
                expect(section.locator("time")).to_have_count(1)
                expect(page.locator("[data-hausmeister-model]")).to_have_value("saved-synthetic")
                expect(section).to_have_attribute("data-ollama", "unknown", timeout=4000)
                expect(page.locator("[data-hausmeister-model]")).to_have_value("saved-synthetic")
                assert len(probes) == before_expiry
                assert restored_registries == {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in restored_files}
                context.close()
            finally:
                browser.close()
    finally:
        if attacker is not None:
            attacker.shutdown()
            attacker.server_close()
        if attacker_worker:
            attacker_worker.join(timeout=5)
        server.should_exit = True
        worker.join(timeout=10)
        listener.close()
        assert not worker.is_alive()
