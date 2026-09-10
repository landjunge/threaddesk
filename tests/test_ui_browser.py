"""Echte Bedienprüfung der Karte in einem Browser.

Der Bauplan verlangt pro Phase eine echte Bedienprüfung. Serverseitige Tests
sehen nur das ausgelieferte HTML: sie bemerken nicht, wenn ein unsichtbares
Overlay jeden Klick schluckt oder Zoom den Inhalt aus dem Bild schiebt.
Diese Tests laufen gegen den lokalen Server in einem echten Chromium.
"""

from __future__ import annotations

import os
import socket
import threading
import time

import pytest

pytest.importorskip("playwright.sync_api", reason="playwright nicht installiert")

from playwright.sync_api import sync_playwright  # noqa: E402

from threaddesk.ui.server import create_app  # noqa: E402


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="module")
def live_map(tmp_path_factory):
    """Startet den echten Server mit einem kleinen Graphen und liefert die URL."""
    uvicorn = pytest.importorskip("uvicorn", reason="uvicorn nicht installiert")
    home = tmp_path_factory.mktemp("threaddesk-home")

    # THREADDESK_HOME ist der Isolationshaken des Servers. HOME taugt nicht:
    # JsonStore.DEFAULT_ROOT wird beim Import festgelegt, nicht beim Aufruf.
    previous = os.environ.get("THREADDESK_HOME")
    os.environ["THREADDESK_HOME"] = str(home)
    try:
        from threaddesk.api.service import ThreadService
        from threaddesk.storage.json_store import JsonStore

        svc = ThreadService(store=JsonStore(home))
        project = svc.create_node("project", "ThreadDesk", status="active",
                                  details="Wurzelprojekt")
        task = svc.create_node("task", "Vereinfachte Karte", status="in_progress",
                               details="Ansicht auf den Wissensgraphen")
        person = svc.create_node("person", "landjunge", status="active")
        svc.connect(project.id, task.id, "contains")
        svc.connect(task.id, person.id, "assigned_to")

        port = _free_port()
        config = uvicorn.Config(create_app(), host="127.0.0.1", port=port,
                                log_level="error")
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        deadline = time.time() + 20
        while not server.started and time.time() < deadline:
            time.sleep(0.05)
        if not server.started:
            pytest.skip("lokaler Server startete nicht")
        yield f"http://127.0.0.1:{port}", 3
        server.should_exit = True
        thread.join(timeout=10)
    finally:
        if previous is None:
            os.environ.pop("THREADDESK_HOME", None)
        else:
            os.environ["THREADDESK_HOME"] = previous


@pytest.fixture(scope="module")
def page(live_map):
    base_url, _ = live_map
    with sync_playwright() as play:
        # In CI liefert `playwright install chromium` den passenden Browser.
        # THREADDESK_CHROMIUM erlaubt einen vorhandenen Browser, wenn die
        # Umgebung keinen passenden Build herunterladen kann.
        executable = os.environ.get("THREADDESK_CHROMIUM") or None
        try:
            browser = play.chromium.launch(executable_path=executable)
        except Exception as exc:  # pragma: no cover - Umgebung ohne Browser
            pytest.skip(f"kein Chromium verfügbar: {exc}")
        tab = browser.new_page(viewport={"width": 1280, "height": 900})
        tab.goto(f"{base_url}/map", wait_until="networkidle")
        tab.wait_for_selector(".map-node", timeout=15000)
        yield tab
        browser.close()


def test_no_overlay_swallows_node_clicks(page):
    """Ein Klick in die Knotenmitte muss den Knoten treffen, kein Overlay."""
    hit = page.evaluate(
        """() => {
            const box = document.querySelector('.map-node').getBoundingClientRect();
            const el = document.elementFromPoint(
                box.x + box.width / 2, box.y + box.height / 2);
            return el.closest('.map-node') ? 'map-node' : el.tagName
                + '.' + (el.className.baseVal ?? el.className);
        }"""
    )
    assert hit == "map-node", f"Klick landet auf {hit} statt auf dem Knoten"


def test_click_selects_node_and_fills_detail(page):
    page.click("[data-map-reset]")
    page.locator(".map-node").first.click()
    assert page.locator(".map-node.is-selected").count() == 1
    assert page.locator("[data-map-detail-title]").inner_text() != "Kein Knoten gewählt"
    assert page.locator("[data-map-detail-meta]").is_visible()


def test_shift_click_collects_and_plain_click_resets(page):
    page.click("[data-map-reset]")
    nodes = page.locator(".map-node")
    nodes.nth(0).click()
    nodes.nth(1).click(modifiers=["Shift"])
    nodes.nth(2).click(modifiers=["Shift"])
    assert page.locator(".map-node.is-selected").count() == 3
    nodes.nth(0).click()
    assert page.locator(".map-node.is-selected").count() == 1


def test_keyboard_selects_node(page):
    page.click("[data-map-reset]")
    page.locator(".map-node").nth(1).focus()
    page.keyboard.press("Enter")
    assert page.locator(".map-node.is-selected").count() == 1


def _visible_nodes(page) -> tuple[int, int]:
    return tuple(page.evaluate(
        """() => {
            const stage = document.querySelector('[data-map-stage]')
                .getBoundingClientRect();
            const nodes = [...document.querySelectorAll('.map-node')];
            const inside = nodes.filter(g => {
                const b = g.getBoundingClientRect();
                return b.left >= stage.left - 1 && b.right <= stage.right + 1
                    && b.top >= stage.top - 1 && b.bottom <= stage.bottom + 1;
            }).length;
            return [inside, nodes.length];
        }"""
    ))


def _centre_offset(page) -> tuple[float, float]:
    """Abstand der Graphmitte zur Bühnenmitte, in Bildschirmpixeln."""
    return tuple(page.evaluate(
        """() => {
            const stage = document.querySelector('[data-map-stage]')
                .getBoundingClientRect();
            const boxes = [...document.querySelectorAll('.map-node')]
                .map(g => g.getBoundingClientRect());
            const cx = (Math.min(...boxes.map(b => b.left))
                + Math.max(...boxes.map(b => b.right))) / 2;
            const cy = (Math.min(...boxes.map(b => b.top))
                + Math.max(...boxes.map(b => b.bottom))) / 2;
            return [Math.abs(cx - (stage.left + stage.width / 2)),
                    Math.abs(cy - (stage.top + stage.height / 2))];
        }"""
    ))


def test_zoom_keeps_content_centred(page):
    """Zoom muss um die Bildmitte verankert sein.

    Hineinzoomen darf weniger Knoten zeigen — das ist der Zweck. Es darf den
    Graphen aber nicht in eine Ecke schieben. Genau das passierte, solange um
    den Nullpunkt der Karte statt um die Bildmitte skaliert wurde.
    """
    page.click("[data-map-reset]")
    page.wait_for_timeout(120)
    before = _centre_offset(page)
    for _ in range(3):
        page.click("[data-map-zoom-in]")
        page.wait_for_timeout(80)
    after = _centre_offset(page)
    assert after[0] <= max(before[0], 1) + 20 and after[1] <= max(before[1], 1) + 20, (
        f"Graphmitte wandert beim Zoom von {before} nach {after}")


def test_fit_restores_full_graph(page):
    for _ in range(4):
        page.click("[data-map-zoom-in]")
    page.click("[data-map-reset]")
    page.wait_for_timeout(150)
    inside, total = _visible_nodes(page)
    assert inside == total, f"Einpassen zeigt nur {inside} von {total} Knoten"


@pytest.mark.parametrize("width", [1280, 600])
def test_pan_follows_the_cursor(page, width):
    """Der Inhalt muss dem Cursor folgen, unabhängig von der Fensterbreite."""
    page.set_viewport_size({"width": width, "height": 900})
    page.click("[data-map-reset]")
    page.wait_for_timeout(150)
    stage = page.locator("[data-map-stage]").bounding_box()
    before = page.evaluate(
        "() => document.querySelector('.map-node').getBoundingClientRect().x")
    start_x = stage["x"] + stage["width"] / 2
    start_y = stage["y"] + stage["height"] / 2
    page.mouse.move(start_x, start_y)
    page.mouse.down()
    page.mouse.move(start_x + 150, start_y, steps=10)
    page.mouse.up()
    page.wait_for_timeout(100)
    after = page.evaluate(
        "() => document.querySelector('.map-node').getBoundingClientRect().x")
    moved = after - before
    assert abs(moved - 150) <= 8, (
        f"Cursor 150px, Inhalt {moved:.1f}px bei Fensterbreite {width}")


def test_shift_click_does_not_select_label_text(page):
    """Shift-Klick sammelt Knoten — er darf nicht nebenbei Text markieren."""
    page.click("[data-map-reset]")
    nodes = page.locator(".map-node")
    nodes.nth(0).click()
    nodes.nth(1).click(modifiers=["Shift"])
    selected_text = page.evaluate("() => window.getSelection().toString()")
    assert selected_text == "", f"Shift-Klick markierte Text: {selected_text!r}"
