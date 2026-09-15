"""Observable Playwright migration journeys with deliberate mouse/keyboard pacing."""

from __future__ import annotations

import os
import socket
import threading
import time
from pathlib import Path
import zipfile

import pytest

pytest.importorskip("playwright.sync_api", reason="playwright not installed")

from playwright.sync_api import expect, sync_playwright  # noqa: E402

from test_atomic_import import write_import_bundle  # noqa: E402
from threaddesk.core.models import KnowledgeNode  # noqa: E402
from threaddesk.services.migration import AtomicImportService, DryRunPlanner, validate_bundle  # noqa: E402
from threaddesk.storage.sqlite_store import SQLiteStore  # noqa: E402
from threaddesk.ui.server import create_app  # noqa: E402

USER_PACE_MS = 180


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def live_migration(tmp_path: Path):
    """A fresh installed-like local workspace for every user journey."""
    uvicorn = pytest.importorskip("uvicorn", reason="uvicorn not installed")
    home = tmp_path / "migration-workspace"
    home.mkdir()
    bundle = write_import_bundle(tmp_path / "notion.tdbundle")
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


def _choose_bundle(page, bundle: Path) -> None:
    page.locator('[data-testid="bundle-file"]').set_input_files({
        "name": bundle.name,
        "mimeType": "application/octet-stream",
        "buffer": bundle.read_bytes(),
    })
    page.wait_for_timeout(USER_PACE_MS)


def _preview(page) -> None:
    page.locator('[data-testid="run-dry-run"]').click()
    page.wait_for_timeout(USER_PACE_MS)


def _import(page) -> None:
    page.locator('[data-testid="import-confirm"]').click()
    page.wait_for_timeout(USER_PACE_MS)


def _copy_bundle(source: Path, target: Path, *, replace: dict[str, bytes] | None = None,
                 extra: dict[str, bytes] | None = None) -> Path:
    replace = replace or {}
    extra = extra or {}
    with zipfile.ZipFile(source, "r") as old, zipfile.ZipFile(
        target, "w", compression=zipfile.ZIP_DEFLATED
    ) as new:
        for info in old.infolist():
            new.writestr(info.filename, replace.get(info.filename, old.read(info.filename)))
        for name, data in extra.items():
            new.writestr(name, data)
    return target


def _commit_for_conflict(home: Path, bundle: Path) -> None:
    store = SQLiteStore(home)
    validated = validate_bundle(bundle)
    plan = DryRunPlanner().plan(
        validated,
        existing_nodes=store.list_nodes(),
        source_records=store.list_source_records("notion"),
    )
    AtomicImportService(store).commit(validated, plan)
    node = next(item for item in store.list_nodes() if item.kind == "project")
    node.details = "Local change must remain visible."
    node.revision += 1
    store.save_node(node)


def test_user_reviews_then_explicitly_imports_bundle_and_creates_recovery_copy(
    live_migration,
):
    base_url, bundle, home = live_migration
    with sync_playwright() as play:
        browser = play.chromium.launch(slow_mo=USER_PACE_MS)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(f"{base_url}/migration", wait_until="networkidle")
        _choose_bundle(page, bundle)
        expect(page.locator('[data-testid="import-confirm"]')).to_be_disabled()
        _preview(page)
        expect(page.locator('[data-testid="import-confirm"]')).to_be_enabled(timeout=15000)
        assert SQLiteStore(home).list_nodes() == []
        _import(page)
        expect(page.locator('[data-migration-summary]')).to_contain_text(
            "Import fertig", timeout=15000,
        )
        assert len(SQLiteStore(home).list_nodes()) == 2
        expect(page.locator('[data-testid="migration-recover"]')).to_be_visible()
        page.locator('[data-testid="migration-recover"]').click()
        expect(page.locator('[data-migration-summary]')).to_contain_text(
            "Wiederherstellungs-Kopie erstellt", timeout=15000,
        )
        assert list((home / "recovery").glob("*"))
        browser.close()


def test_user_reimports_identical_bundle_without_duplicate_nodes_or_backups(
    live_migration,
):
    base_url, bundle, home = live_migration
    with sync_playwright() as play:
        browser = play.chromium.launch(slow_mo=USER_PACE_MS)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(f"{base_url}/migration", wait_until="networkidle")

        _choose_bundle(page, bundle)
        _preview(page)
        expect(page.locator('[data-testid="import-confirm"]')).to_be_enabled(timeout=15000)
        _import(page)
        expect(page.locator('[data-migration-summary]')).to_contain_text(
            "Import fertig", timeout=15000,
        )
        backups = list((home / "backups").glob("*.complete"))

        _choose_bundle(page, bundle)
        _preview(page)
        expect(page.locator('[data-testid="import-confirm"]')).to_be_enabled(timeout=15000)
        _import(page)
        expect(page.locator('[data-migration-summary]')).to_contain_text(
            "Import fertig", timeout=15000,
        )
        assert len(SQLiteStore(home).list_nodes()) == 2
        assert list((home / "backups").glob("*.complete")) == backups
        browser.close()


def test_user_keeps_local_conflict_with_keyboard_then_imports(
    live_migration, tmp_path: Path,
):
    base_url, _, home = live_migration
    first = write_import_bundle(tmp_path / "first.tdbundle")
    changed = write_import_bundle(
        tmp_path / "changed.tdbundle", export_id="export-2",
        project_title="ThreadDesk changed in Notion",
    )
    _commit_for_conflict(home, first)

    with sync_playwright() as play:
        browser = play.chromium.launch(slow_mo=USER_PACE_MS)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(f"{base_url}/migration", wait_until="networkidle")
        _choose_bundle(page, changed)
        _preview(page)
        expect(page.locator('[data-migration-summary]')).to_contain_text(
            "Prüfung blockiert: conflict", timeout=15000,
        )
        comparison = page.locator('[data-conflict-source="page-project"]')
        expect(comparison).to_contain_text("ThreadDesk-Stand")
        expect(comparison).to_contain_text("Local change must remain visible.")
        expect(comparison).to_contain_text("Notion-Vorschlag")
        expect(comparison).to_contain_text("ThreadDesk changed in Notion")
        choice = page.locator(
            '[data-conflict-source="page-project"] [data-action="keep_local"]'
        )
        expect(choice).to_be_visible()
        choice.focus()
        page.keyboard.press("Enter")
        expect(choice).to_have_attribute("aria-pressed", "true")
        expect(page.locator('[data-testid="import-confirm"]')).to_be_enabled()
        _import(page)
        expect(page.locator('[data-migration-summary]')).to_contain_text(
            "Import fertig", timeout=15000,
        )
        assert len(SQLiteStore(home).list_nodes()) == 2
        local = next(
            item for item in SQLiteStore(home).list_nodes() if item.kind == "project"
        )
        assert local.details == "Local change must remain visible."
        browser.close()


def test_user_takes_notion_conflict_with_mouse_then_imports(
    live_migration, tmp_path: Path,
):
    base_url, _, home = live_migration
    first = write_import_bundle(tmp_path / "first.tdbundle")
    changed = write_import_bundle(
        tmp_path / "changed.tdbundle", export_id="export-2",
        project_title="ThreadDesk changed in Notion",
    )
    _commit_for_conflict(home, first)

    with sync_playwright() as play:
        browser = play.chromium.launch(slow_mo=USER_PACE_MS)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(f"{base_url}/migration", wait_until="networkidle")
        _choose_bundle(page, changed)
        _preview(page)
        choice = page.locator(
            '[data-conflict-source="page-project"] [data-action="take_source"]'
        )
        expect(choice).to_be_visible(timeout=15000)
        choice.click()
        expect(choice).to_have_attribute("aria-pressed", "true")
        expect(page.locator('[data-testid="import-confirm"]')).to_be_enabled()
        _import(page)
        expect(page.locator('[data-migration-summary]')).to_contain_text(
            "Import fertig", timeout=15000,
        )
        imported = next(
            item for item in SQLiteStore(home).list_nodes() if item.kind == "project"
        )
        assert imported.title == "ThreadDesk changed in Notion"
        browser.close()


@pytest.mark.parametrize(
    ("name", "builder", "error"),
    [
        (
            "checksum",
            lambda source, target: _copy_bundle(
                source, target,
                replace={"content/page-task.md": b"# changed without manifest hash\n"},
            ),
            "size",
        ),
        (
            "path",
            lambda source, target: _copy_bundle(
                source, target, extra={"../outside.md": b"not allowed"},
            ),
            "path",
        ),
        (
            "zip-bomb",
            lambda source, target: _copy_bundle(
                source, target, extra={"content/repeated.md": b"0" * 4096},
            ),
            "compression_ratio",
        ),
    ],
)
def test_user_sees_unsafe_bundle_rejected_without_partial_import(
    live_migration, tmp_path: Path, name, builder, error,
):
    base_url, source, home = live_migration
    unsafe = builder(source, tmp_path / f"{name}.tdbundle")
    with sync_playwright() as play:
        browser = play.chromium.launch(slow_mo=USER_PACE_MS)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(f"{base_url}/migration", wait_until="networkidle")
        _choose_bundle(page, unsafe)
        _preview(page)
        expect(page.locator('[data-migration-summary]')).to_contain_text(
            f"Prüfung nicht möglich: {error}", timeout=15000,
        )
        expect(page.locator('[data-testid="import-confirm"]')).to_be_disabled()
        assert SQLiteStore(home).list_nodes() == []
        browser.close()


def test_user_sees_secret_rejected_without_exposing_secret_or_importing(
    live_migration, tmp_path: Path,
):
    base_url, _, home = live_migration
    unsafe = write_import_bundle(
        tmp_path / "secret.tdbundle", project_title="API_KEY=placeholder",
    )
    with sync_playwright() as play:
        browser = play.chromium.launch(slow_mo=USER_PACE_MS)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(f"{base_url}/migration", wait_until="networkidle")
        _choose_bundle(page, unsafe)
        _preview(page)
        expect(page.locator('[data-migration-summary]')).to_contain_text(
            "Prüfung nicht möglich: secret", timeout=15000,
        )
        expect(page.locator('[data-migration-summary]')).not_to_contain_text(
            "placeholder",
        )
        expect(page.locator('[data-testid="import-confirm"]')).to_be_disabled()
        assert SQLiteStore(home).list_nodes() == []
        browser.close()


def test_english_user_can_review_import_and_create_recovery_copy(live_migration):
    base_url, bundle, home = live_migration
    with sync_playwright() as play:
        browser = play.chromium.launch(slow_mo=USER_PACE_MS)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(f"{base_url}/migration?lang=en", wait_until="networkidle")
        expect(page.locator("html")).to_have_attribute("lang", "en")
        _choose_bundle(page, bundle)
        expect(page.locator('[data-testid="import-confirm"]')).to_be_disabled()
        _preview(page)
        expect(page.locator('[data-migration-summary]')).to_contain_text(
            "Preview ready", timeout=15000,
        )
        expect(page.locator('[data-testid="import-confirm"]')).to_be_enabled()
        _import(page)
        expect(page.locator('[data-migration-summary]')).to_contain_text(
            "Import complete", timeout=15000,
        )
        page.locator('[data-testid="migration-recover"]').click()
        expect(page.locator('[data-migration-summary]')).to_contain_text(
            "Recovery copy created", timeout=15000,
        )
        assert len(SQLiteStore(home).list_nodes()) == 2
        browser.close()
