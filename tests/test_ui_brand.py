"""Die Desktop-App und die Tafel tragen die aktuelle ThreadDesk-Bildmarke."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BRAND = ROOT / "brand"
STATIC = ROOT / "src" / "threaddesk" / "ui" / "static"
TEMPLATE = ROOT / "src" / "threaddesk" / "ui" / "templates" / "base.html"
SPEC = ROOT / "packaging" / "ThreadDesk.spec"


def test_packaged_mark_matches_brand_source() -> None:
    shipped = STATIC / "mark.svg"
    source = BRAND / "mark.svg"
    assert shipped.is_file(), "ui/static/mark.svg fehlt — Bildmarke kommt aus brand/mark.svg"
    assert shipped.read_bytes() == source.read_bytes()


def test_topbar_and_favicon_use_the_shipped_mark() -> None:
    markup = TEMPLATE.read_text(encoding="utf-8")
    assert 'rel="icon"' in markup
    assert 'href="/static/mark.svg"' in markup
    assert 'src="/static/mark.svg"' in markup
    assert 'class="brand-mark"' in markup
    assert "<img" in markup


def test_desktop_spec_uses_generated_app_icons() -> None:
    spec = SPEC.read_text(encoding="utf-8")
    assert "ThreadDesk.icns" in spec
    assert "ThreadDesk.ico" in spec
    assert "icon=ICON_MAC" in spec
    assert "icon=ICON_WIN" in spec
    assert (BRAND / "ThreadDesk.icns").is_file()
    assert (BRAND / "ThreadDesk.ico").is_file()


def test_ui_serves_the_mark(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    monkeypatch.setenv("THREADDESK_HOME", str(tmp_path))
    from threaddesk.ui.server import create_app

    client = TestClient(create_app())
    page = client.get("/")
    assert page.status_code == 200
    assert "/static/mark.svg" in page.text
    mark = client.get("/static/mark.svg")
    assert mark.status_code == 200
    assert b"<svg" in mark.content
    assert mark.content == (BRAND / "mark.svg").read_bytes()
