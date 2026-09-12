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
        # Deckt alle vier Formen und alle Zustandstöne ab.
        project = svc.create_node("project", "ThreadDesk", status="active",
                                  details="Wurzelprojekt")
        task = svc.create_node("task", "Vereinfachte Karte", status="in_progress",
                               details="Ansicht auf den Wissensgraphen")
        person = svc.create_node("person", "landjunge", status="active")
        decision = svc.create_node("decision", "Local-first, Server optional",
                                   status="confirmed", details="Grundsatz")
        tool = svc.create_node("tool", "MCP-Server", status="active")
        blocked = svc.create_node("task", "Nummerierung td list/switch",
                                  status="blocked", details="Wartet auf PR 1")
        svc.connect(project.id, task.id, "contains")
        svc.connect(task.id, person.id, "assigned_to")
        svc.connect(decision.id, project.id, "supports")
        svc.connect(tool.id, project.id, "supports")
        svc.connect(blocked.id, task.id, "blocks")

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
        yield f"http://127.0.0.1:{port}", 6
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
    # Auf leerer Fläche greifen, sonst wird ein Knoten versetzt statt geschoben.
    spot = page.evaluate(
        """() => {
            const box = document.querySelector('[data-map-stage]')
                .getBoundingClientRect();
            for (let dy = 0.12; dy < 0.9; dy += 0.06) {
                for (let dx = 0.08; dx < 0.95; dx += 0.06) {
                    const x = box.left + box.width * dx;
                    const y = box.top + box.height * dy;
                    const hit = document.elementFromPoint(x, y);
                    if (hit && !hit.closest('.map-node')
                        && !hit.closest('.map-legend')) return [x, y];
                }
            }
            return null;
        }"""
    )
    assert spot, "keine freie Fläche zum Verschieben gefunden"
    start_x, start_y = spot
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


# --------------------------------------------------------------- Darstellung

def test_shape_follows_node_kind(page):
    """Die Form trägt den Typ: Kreis, Rechteck, Dokument, Vieleck."""
    shapes = page.evaluate(
        """() => Object.fromEntries([...document.querySelectorAll('.map-node')]
            .map(g => [g.dataset.kind,
                       [...g.classList].find(c => c.startsWith('map-node-'))]))"""
    )
    assert shapes["project"] == "map-node-circle"
    assert shapes["person"] == "map-node-circle"
    assert shapes["task"] == "map-node-rect"
    assert shapes["decision"] == "map-node-doc"
    assert shapes["tool"] == "map-node-hex"


def test_status_is_readable_without_colour(page):
    """Jeder Knoten trägt zusätzlich zur Farbe eine Statusmarke."""
    missing = page.evaluate(
        """() => [...document.querySelectorAll('.map-node')]
            .filter(g => !g.querySelector('.map-node-mark-sign'))
            .map(g => g.getAttribute('aria-label'))"""
    )
    assert missing == [], f"Knoten ohne Statusmarke: {missing}"


def test_labels_are_not_truncated(page):
    """Beschriftungen stehen unter dem Knoten und werden nicht abgeschnitten."""
    texts = page.evaluate(
        """() => [...document.querySelectorAll('.map-label')]
            .map(g => [...g.querySelectorAll('text')].map(t => t.textContent).join(' '))"""
    )
    assert texts, "keine Beschriftungen gerendert"
    assert not any("…" in text for text in texts), f"abgeschnitten: {texts}"
    assert "Nummerierung td list/switch" in texts


def test_directed_relations_carry_an_arrow(page):
    """Übergaben und Abhängigkeiten zeigen ihre Richtung."""
    arrows = page.evaluate(
        """() => Object.fromEntries([...document.querySelectorAll('.map-edge')]
            .map(p => [p.dataset.relation, Boolean(p.getAttribute('marker-end'))]))"""
    )
    assert arrows.get("assigned_to") is True
    assert arrows.get("blocks") is True
    assert arrows.get("supports") is True
    assert arrows.get("contains") is False


def test_chrome_uses_shared_tokens_and_map_has_its_own_tones(page):
    """Arbeitsteilung: Grundgerüst gedämpft, Karte leuchtend.

    Buttons und Rahmen folgen dem gemeinsamen Netzwerkpunkt-Design. Die
    Landkarte ist der Schauplatz und bringt eigene, leuchtende Zustandstöne
    mit — sonst verschwinden Zustände auf dunklem Grund.
    """
    values = page.evaluate(
        """() => {
            const map = getComputedStyle(document.querySelector('.map-page'));
            const root = getComputedStyle(document.documentElement);
            const read = (style, name) => style.getPropertyValue(name).trim();
            return {
                accent: read(root, '--accent'),
                mutedOk: read(root, '--ok'),
                toneGood: read(map, '--tone-good'),
                toneRisk: read(map, '--tone-risk'),
            };
        }"""
    )
    # Grundgeruest folgt dem gemeinsamen Akzent aller Werkzeuge.
    assert values["accent"].lower() == "#8f98a8"
    # Die Karte übernimmt ihn gerade nicht.
    assert values["toneGood"] != values["mutedOk"]
    assert values["toneGood"] and values["toneRisk"]


def test_every_tone_is_visibly_distinct(page):
    """Die vier Zustandstöne müssen sich auf der Karte klar unterscheiden."""
    tones = page.evaluate(
        """() => {
            const style = getComputedStyle(document.querySelector('.map-page'));
            return ['good', 'wait', 'fresh', 'risk', 'idle']
                .map(name => style.getPropertyValue('--tone-' + name).trim());
        }"""
    )
    assert len(set(tones)) == len(tones), f"Töne nicht eindeutig: {tones}"


# --------------------------------------------------------------- Effekte

def test_effects_can_be_switched_off(page):
    """Effekte sind abschaltbar — der Bauplan verlangt das ausdrücklich."""
    toggle = page.locator("[data-map-effects]")
    page_root = page.locator(".map-page")
    if "effects-off" in (page_root.get_attribute("class") or ""):
        toggle.click()
    assert "effects-off" not in (page_root.get_attribute("class") or "")
    assert toggle.get_attribute("aria-pressed") == "true"
    toggle.click()
    assert "effects-off" in (page_root.get_attribute("class") or "")
    assert toggle.get_attribute("aria-pressed") == "false"
    animation = page.evaluate(
        """() => {
            const edge = document.querySelector('.map-edge-flow');
            return edge ? getComputedStyle(edge).animationName : 'none';
        }"""
    )
    assert animation == "none", f"Animation läuft trotz Abschaltung: {animation}"
    toggle.click()


def test_reduced_motion_stops_animation(page):
    """Wer weniger Bewegung verlangt, bekommt keine."""
    page.emulate_media(reduced_motion="reduce")
    page.reload(wait_until="networkidle")
    page.wait_for_selector(".map-node")
    try:
        classes = page.locator(".map-page").get_attribute("class") or ""
        assert "effects-off" in classes, "Effekte laufen trotz reduzierter Bewegung"
        animation = page.evaluate(
            """() => {
                const edge = document.querySelector('.map-edge-flow');
                return edge ? getComputedStyle(edge).animationName : 'none';
            }"""
        )
        assert animation == "none", f"Animation läuft trotzdem: {animation}"
    finally:
        page.emulate_media(reduced_motion="no-preference")
        page.reload(wait_until="networkidle")
        page.wait_for_selector(".map-node")


def test_node_can_be_dragged(page):
    """Knoten lassen sich versetzen, ohne die Auswahl auszulösen."""
    page.click("[data-map-reset]")
    page.wait_for_timeout(120)
    node = page.locator(".map-node").first
    box = node.bounding_box()
    start_x = box["x"] + box["width"] / 2
    start_y = box["y"] + box["height"] / 2
    page.mouse.move(start_x, start_y)
    page.mouse.down()
    page.mouse.move(start_x + 90, start_y + 40, steps=12)
    page.mouse.up()
    page.wait_for_timeout(120)
    moved = node.bounding_box()
    assert abs(moved["x"] - box["x"]) > 30, "Knoten ließ sich nicht versetzen"


def test_wordmark_is_branded_but_ui_is_not(page):
    """Violett gehört dem Schriftzug, nicht der Oberfläche.

    Wie auf threaddesk.netzwerkpunkt.de und in brand/wordmark.svg steht
    „Thread" in der Markenfarbe und „Desk" in der Textfarbe. Der Akzent der
    Oberfläche — Knöpfe, Fokus, aktive Navigation — bleibt davon unberührt.
    """
    parts = page.evaluate(
        """() => {
            const name = document.querySelector('.brand-name');
            const thread = name.querySelector('.brand-thread');
            const root = getComputedStyle(document.documentElement);
            return {
                full: name.textContent.trim(),
                thread: thread ? thread.textContent : null,
                threadColour: thread ? getComputedStyle(thread).color : null,
                brand: root.getPropertyValue('--brand').trim(),
                accent: root.getPropertyValue('--accent').trim(),
            };
        }"""
    )
    assert parts["full"] == "ThreadDesk"
    assert parts["thread"] == "Thread"
    assert parts["brand"].lower() == "#b99cff"
    # Der Schriftzug trägt die Markenfarbe ...
    assert parts["threadColour"] == "rgb(185, 156, 255)"
    # ... die Oberfläche ausdrücklich nicht.
    assert parts["accent"].lower() != parts["brand"].lower()
