"""Playwright acceptance test: a reviewed bundle needs a second explicit import click."""

from __future__ import annotations

import os
import socket
import threading
import time

import pytest

pytest.importorskip("playwright.sync_api", reason="playwright not installed")

from playwright.sync_api import expect, sync_playwright  # noqa: E402

from test_atomic_import import write_import_bundle  # noqa: E402
from threaddesk.storage.sqlite_store import SQLiteStore  # noqa: E402
from threaddesk.ui.server import create_app  # noqa: E402


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="module")
def live_migration(tmp_path_factory):
    uvicorn = pytest.importorskip("uvicorn", reason="uvicorn not installed")
    home = tmp_path_factory.mktemp("migration-workspace")
    bundle = write_import_bundle(home / "notion.tdbundle")
    before_home = os.environ.get("THREADDESK_HOME")
    before_storage = os.environ.get("THREADDESK_STORAGE")
    os.environ["THREADDESK_HOME"] = str(home)
    os.environ["THREADDESK_STORAGE"] = "sqlite"
    try:
        SQLiteStore(home)
        port = _free_port()
        server = uvicorn.Server(uvicorn.Config(
            create_app(), host="127.0.0.1", port=port, log_level="error",
        ))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        deadline = time.time() + 20
        while not server.started and time.time() < deadline:
            time.sleep(0.05)
        if not server.started:
            pytest.skip("local migration server did not start")
        yield f"http://127.0.0.1:{port}", bundle, home
        server.should_exit = True
        thread.join(timeout=10)
    finally:
        if before_home is None:
            os.environ.pop("THREADDESK_HOME", None)
        else:
            os.environ["THREADDESK_HOME"] = before_home
        if before_storage is None:
            os.environ.pop("THREADDESK_STORAGE", None)
        else:
            os.environ["THREADDESK_STORAGE"] = before_storage


def test_user_reviews_then_explicitly_imports_bundle(live_migration):
    base_url, bundle, home = live_migration
    with sync_playwright() as play:
        browser = play.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(f"{base_url}/migration", wait_until="networkidle")
        page.locator('[data-testid="bundle-file"]').set_input_files({
            "name": "notion.tdbundle",
            "mimeType": "application/octet-stream",
            "buffer": bundle.read_bytes(),
        })
        page.wait_for_timeout(180)
        expect(page.locator('[data-testid="import-confirm"]')).to_be_disabled()
        page.locator('[data-testid="run-dry-run"]').click()
        expect(page.locator('[data-testid="import-confirm"]')).to_be_enabled(timeout=15000)
        assert SQLiteStore(home).list_nodes() == []
        page.wait_for_timeout(180)
        page.locator('[data-testid="import-confirm"]').click()
        expect(page.locator('[data-migration-summary]')).to_contain_text(
            "Import fertig", timeout=15000,
        )
        assert len(SQLiteStore(home).list_nodes()) == 2
        expect(page.locator('[data-testid="migration-recover"]')).to_be_visible()
        page.wait_for_timeout(180)
        page.locator('[data-testid="migration-recover"]').click()
        expect(page.locator('[data-migration-summary]')).to_contain_text(
            "Wiederherstellungs-Kopie erstellt", timeout=15000,
        )
        browser.close()
