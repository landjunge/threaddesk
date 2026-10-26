"""Real graph workspace geometry and user actions on a representative local graph."""
from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright
from test_desk_browser import Desk

from threaddesk.api.service import ThreadService
from threaddesk.services.library_batch import LibraryBatchImporter
from threaddesk.storage.json_store import JsonStore

VIEWPORTS = [(1440, 900), (1180, 760)]
SHOTS = Path(os.environ.get("THREADDESK_GRAPH_SHOTS", "/tmp/td-graph-repair-20261026"))


def _settle(page):
    page.evaluate("() => new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done)))")


def _screenshot(page, viewport, label):
    SHOTS.mkdir(parents=True, exist_ok=True)
    phase = os.environ.get("THREADDESK_GRAPH_SHOT_PHASE", "after")
    page.screenshot(path=str(SHOTS / f"{phase}-{viewport[0]}x{viewport[1]}-{label}.png"), full_page=True)
    (SHOTS / f"{phase}-{viewport[0]}x{viewport[1]}-{label}.json").write_text(
        json.dumps({"geometry": _geometry(page), "labels": _readability(page)}, indent=2))


def _readability(page):
    return page.locator("[data-map-stage]").evaluate("""stage => {
      const box = element => {
        const r=element.getBoundingClientRect();
        return {x:r.x,y:r.y,width:r.width,height:r.height};
      };
      const intersects=(a,b) => Math.min(a.x+a.width,b.x+b.width)-Math.max(a.x,b.x)>1 &&
        Math.min(a.y+a.height,b.y+b.height)-Math.max(a.y,b.y)>1;
      const frame=box(stage);
      const nodes=[...stage.querySelectorAll('.map-node')].filter(node =>
        getComputedStyle(node).display!=='none');
      const shapes=nodes.map(node => ({id:node.dataset.nodeId,box:box(node.querySelector('.map-node-shape'))}));
      const labels=nodes.flatMap(node => {
        const label=node.querySelector('.map-label');
        if (getComputedStyle(label).display==='none') return [];
        const texts=[...label.querySelectorAll('text')];
        const bounds=box(label);
        if (!intersects(bounds,frame)) return [];
        return [{id:node.dataset.nodeId,box:bounds,fonts:texts.map(text => {
          const m=text.getScreenCTM();
          return parseFloat(getComputedStyle(text).fontSize)*Math.hypot(m.c,m.d);
        })}];
      });
      const collisions=[];
      labels.forEach((label,index) => {
        labels.slice(index+1).forEach(other => {
          if (intersects(label.box,other.box)) collisions.push({type:'text',a:label.id,b:other.id});
        });
        shapes.forEach(shape => {
          if (shape.id!==label.id && intersects(label.box,shape.box))
            collisions.push({type:'node',a:label.id,b:shape.id});
        });
      });
      return {nodes:nodes.length,visible:labels.length,labels,collisions};
    }""")


def _geometry(page):
    return page.locator("[data-map-stage]").evaluate("""stage => {
      const rect=stage.getBoundingClientRect();
      const main=document.querySelector('[data-graph-endpoint]').getBoundingClientRect();
      const workspace=document.querySelector('.map-workspace')?.getBoundingClientRect();
      return {width:rect.width,height:rect.height,top:rect.top,bottom:rect.bottom,
        availableHeight:window.innerHeight-Math.max(0,main.top),viewportHeight:window.innerHeight,
        viewportWidth:window.innerWidth,documentWidth:document.documentElement.scrollWidth,
        workspaceWidth:workspace?.width || main.width,
        pageScale:window.visualViewport?.scale || 1,
        documentZoom:getComputedStyle(document.documentElement).zoom,
        bodyZoom:getComputedStyle(document.body).zoom};
    }""")


def _assert_workspace(page):
    geometry = _geometry(page)
    assert geometry["height"] >= 300, geometry
    assert geometry["height"] >= geometry["availableHeight"] * 0.60, geometry
    assert geometry["bottom"] <= geometry["viewportHeight"] + 2, geometry
    assert geometry["documentWidth"] <= geometry["viewportWidth"] + 2, geometry
    assert math.isclose(geometry["pageScale"], 1.0, abs_tol=0.01), geometry
    assert geometry["documentZoom"] in {"1", "normal"}, geometry
    assert geometry["bodyZoom"] in {"1", "normal"}, geometry
    return geometry


def _camera(page):
    return page.locator("[data-map-stage]").evaluate("""stage => {
      const rect=stage.getBoundingClientRect();
      const svg=stage.querySelector('svg');
      const world=stage.querySelector('[data-map-world]');
      const matrix=world.getScreenCTM();
      const point=svg.createSVGPoint();
      point.x=rect.left+rect.width/2; point.y=rect.top+rect.height/2;
      const centre=point.matrixTransform(matrix.inverse());
      return {x:centre.x,y:centre.y,scale:Math.hypot(matrix.a,matrix.b)};
    }""")


def _assert_same_camera(before, after):
    drift = math.hypot(before["x"] - after["x"], before["y"] - after["y"]) * after["scale"]
    assert drift <= 16, {"before": before, "after": after, "screen_drift": drift}
    assert math.isclose(before["scale"], after["scale"], rel_tol=0.02), {"before": before, "after": after}


@pytest.fixture(params=VIEWPORTS, ids=lambda value: f"{value[0]}x{value[1]}")
def graph_workspace(tmp_path, request, monkeypatch):
    home = tmp_path / "workspace"
    store = JsonStore(home)
    service = ThreadService(store=store)
    thread = service.create("Arbeitskarte mit mehreren Projekten und langen nachvollziehbaren Titeln")
    primary = service.create_node("project", "Zentrales Projekt für lange Titel und übersichtliche Dateien",
                                  metadata={"thread_id": thread.id})
    for number in range(25):
        node = service.create_node(
            ("task", "decision", "document", "project")[number % 4],
            f"Bereich {number:02d} – Langer fachlicher Titel für Planung, Quellen und überprüfbare Ergebnisse",
            metadata={} if number == 3 else {"thread_id": thread.id},
        )
        service.connect(primary.id, node.id, "contains")
    source = tmp_path / "originals"
    source.mkdir()
    for number in range(2):
        (source / f"fixture-{number}.txt").write_text(f"Graph workspace preview marker {number}\n")
    batch = LibraryBatchImporter(store)
    imported = batch.run(batch.manifest_for_folder(source.resolve(), thread_id=thread.id, node_id=primary.id),
                         operation_id="graph-workspace-fixture")
    assert imported["complete"], imported
    assert len(service.graph()["nodes"]) == 28
    # Optional pinned source snapshot lets the same behaviour checks prove the
    # regression before a repair, without changing any product file.
    baseline = os.environ.get("THREADDESK_GRAPH_TEST_SOURCE")
    if baseline:
        import test_desk_browser
        monkeypatch.setattr(test_desk_browser, "ROOT", Path(baseline))
    desk = Desk(home)
    url = desk.start()
    viewport = request.param
    try:
        with sync_playwright() as play:
            browser = play.chromium.launch(executable_path=os.environ.get("THREADDESK_CHROMIUM") or None)
            page = browser.new_page(viewport={"width": viewport[0], "height": viewport[1]})
            page_errors = []
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            page.emulate_media(reduced_motion="reduce")
            page.goto(f"{url}/map?lang=de&node={primary.id}", wait_until="networkidle")
            try:
                expect(page.locator(".map-node")).to_have_count(28)
            except AssertionError:
                _screenshot(page, viewport, "load-failure")
                raise AssertionError(f"Graph did not render 28 nodes; browser errors: {page_errors}") from None
            expect(page.locator(f'.map-node[data-node-id="{primary.id}"]')).to_have_class(re.compile("is-selected"))
            _settle(page)
            yield page, viewport, primary, imported["files"][0]["record_id"]
            browser.close()
    finally:
        desk.stop()


def test_graph_remains_large_and_selected_title_readable(graph_workspace):
    page, viewport, primary, _record_id = graph_workspace
    _screenshot(page, viewport, "selected-graph")
    geometry = _assert_workspace(page)
    label = page.locator(f'.map-node[data-node-id="{primary.id}"] .map-label text').first
    expect(label).to_be_visible()
    metrics = label.evaluate("""text => {
      const matrix=text.getScreenCTM();
      const rect=text.getBoundingClientRect();
      return {screenFont:parseFloat(getComputedStyle(text).fontSize)*Math.hypot(matrix.c,matrix.d),
        width:rect.width,height:rect.height};
    }""")
    assert metrics["screenFont"] >= 15.9, {"target_pixels": 16, **metrics, "stage": geometry}
    assert metrics["height"] > 0 and metrics["width"] > 0, metrics


def test_overview_titles_remain_readable_without_overlap(graph_workspace):
    page, viewport, _primary, _record_id = graph_workspace
    if page.locator("[data-map-inspector]").is_visible():
        page.locator("[data-map-inspector-close]").click()
    page.locator("[data-map-reset]").click()
    _settle(page)
    _assert_workspace(page)
    _screenshot(page, viewport, "overview-readability")
    metrics = _readability(page)
    assert metrics["visible"] >= math.ceil(metrics["nodes"] / 2), metrics
    assert not [collision for collision in metrics["collisions"]
                if collision["type"] == "text" or collision["a"] == _primary.id], metrics
    assert all(font >= 13.9 for label in metrics["labels"] for font in label["fonts"]), metrics


def test_focus_and_graph_search_type_project_filters(graph_workspace):
    page, viewport, primary, _record_id = graph_workspace
    focus = page.locator("[data-map-focus-selection]")
    expect(focus).to_be_enabled()
    focus.click()
    _settle(page)
    assert _camera(page)["scale"] >= 0.99
    before_zoom = _camera(page)
    page.locator("[data-map-zoom-in]").click()
    _settle(page)
    after_zoom = _camera(page)
    assert math.hypot(before_zoom["x"] - after_zoom["x"], before_zoom["y"] - after_zoom["y"]) < 1
    assert math.isclose(after_zoom["scale"], before_zoom["scale"] * 1.25, rel_tol=0.02)
    node = page.locator(f'.map-node[data-node-id="{primary.id}"] .map-node-shape')
    node_box = node.bounding_box()
    stage_box = page.locator("[data-map-stage]").bounding_box()
    assert node_box and stage_box
    assert abs(node_box["x"] + node_box["width"] / 2 - stage_box["x"] - stage_box["width"] / 2) <= 4
    assert abs(node_box["y"] + node_box["height"] / 2 - stage_box["y"] - stage_box["height"] / 2) <= 4
    page.locator("[data-map-query]").fill("Bereich 03")
    page.locator("[data-map-query]").press("Enter")
    expect(page.locator(".map-node:visible")).to_have_count(1)
    expect(focus).to_be_disabled()
    expect(page.locator(".map-node:visible")).to_have_attribute("aria-label", re.compile("Bereich 03"))
    page.locator("[data-map-clear-filters]").click()
    expect(page.locator(".map-node:visible")).to_have_count(28)
    expect(focus).to_be_enabled()
    page.locator("[data-map-kind]").select_option("task")
    expect(page.locator(".map-node:visible")).to_have_count(7)
    assert set(page.locator(".map-node:visible").evaluate_all("nodes => nodes.map(node=>node.dataset.kind)")) == {"task"}
    page.locator("[data-map-kind]").select_option("")
    isolated_project = page.locator("[data-map-project] option").filter(has_text="Bereich 03").get_attribute("value")
    page.locator("[data-map-project]").select_option(isolated_project)
    expect(page.locator(".map-node:visible")).to_have_count(1)
    expect(focus).to_be_disabled()
    page.locator("[data-map-project]").select_option(primary.id)
    expect(page.locator(".map-node:visible")).to_have_count(28)
    page.locator("[data-map-query]").fill("kein vorhandener Titel")
    page.locator("[data-map-query]").press("Enter")
    expect(page.locator(".map-node:visible")).to_have_count(0)
    expect(page.locator("[data-map-empty]")).to_be_visible()
    expect(focus).to_be_disabled()
    page.locator("[data-map-clear-filters]").click()
    expect(page.locator(".map-node:visible")).to_have_count(28)
    _assert_workspace(page)
    _screenshot(page, viewport, "filters-cleared")


def test_inspector_file_action_and_resize_preserve_workspace_and_camera(graph_workspace):
    page, viewport, primary, record_id = graph_workspace
    inspector = page.locator("[data-map-inspector]")
    if inspector.is_visible():
        page.locator("[data-map-inspector-close]").click()
    expect(inspector).not_to_be_visible()
    _settle(page)
    closed = _assert_workspace(page)
    page.locator("[data-map-inspector-toggle]").click()
    expect(inspector).to_be_visible()
    page.locator('[data-map-tab="selection"]').click()
    expect(page.locator('[data-map-pane="selection"]')).to_be_visible()
    expect(page.locator('[data-map-detail-title]')).to_have_text(primary.title)
    _settle(page)
    opened = _assert_workspace(page)
    assert opened["height"] >= closed["height"] * 0.95, {"closed": closed, "opened": opened}
    assert opened["width"] >= opened["workspaceWidth"] * 0.60, opened
    page.locator('[data-map-tab="files"]').click()
    expect(page.locator('[data-map-pane="files"]')).to_be_visible()
    panel = page.locator("[data-graph-files]")
    file_button = panel.locator(f'[data-file-record="{record_id}"]')
    expect(file_button).to_be_visible()
    _settle(page)
    camera = _camera(page)
    file_button.click()
    expect(panel.locator("[data-file-preview]")).to_be_visible()
    expect(panel.locator("[data-file-body]")).to_contain_text("Graph workspace preview marker")
    expect(panel.locator("[data-file-assignments]")).to_contain_text(primary.title)
    _assert_workspace(page)
    _screenshot(page, viewport, "file-preview")
    panel.locator("[data-file-name]").fill("renamed-workspace.txt")
    with page.expect_response(lambda response: "/api/graph" in response.url):
        panel.locator('[data-file-action="rename"]').click()
    expect(panel.locator("[data-file-title]")).to_have_text("renamed-workspace.txt")
    panel.locator("[data-file-close]").click()
    _settle(page)
    _assert_workspace(page)
    _assert_same_camera(camera, _camera(page))
    page.locator('[data-map-tab="selection"]').click()
    expect(page.locator('[data-map-detail-title]')).to_have_text(primary.title)
    page.locator("[data-map-inspector-close]").click()
    _settle(page)
    before_resize = _camera(page)
    other = VIEWPORTS[1] if viewport == VIEWPORTS[0] else VIEWPORTS[0]
    page.set_viewport_size({"width": other[0], "height": other[1]})
    _settle(page)
    _assert_workspace(page)
    _assert_same_camera(before_resize, _camera(page))
    expect(page.locator(f'.map-node[data-node-id="{primary.id}"]')).to_have_class(re.compile("is-selected"))
    _screenshot(page, other, "resized-workspace")


@pytest.mark.parametrize("graph_workspace", [(940, 640)], indirect=True, ids=["940x640"])
def test_compact_overview_node_shapes_remain_individually_clickable(graph_workspace):
    page, viewport, primary, _record_id = graph_workspace
    if page.locator("[data-map-inspector]").is_visible():
        page.locator("[data-map-inspector-close]").click()
    page.locator("[data-map-reset]").click()
    page.mouse.move(0, 0)
    _settle(page)
    hits = page.locator("[data-map-stage]").evaluate("""stage => {
      const frame=stage.getBoundingClientRect();
      return [...stage.querySelectorAll('.map-node')].flatMap(node => {
        if (getComputedStyle(node).display==='none') return [];
        const r=node.querySelector('.map-node-shape').getBoundingClientRect();
        const x=r.x+r.width/2,y=r.y+r.height/2;
        if (x<frame.left || x>frame.right || y<frame.top || y>frame.bottom) return [];
        const target=document.elementFromPoint(x,y)?.closest('.map-node');
        return [{expected:node.dataset.nodeId,actual:target?.dataset.nodeId || null,x,y}];
      });
    }""")
    _screenshot(page, viewport, "node-hit-regions")
    assert len(hits) == 28, hits
    blocked = [hit for hit in hits if hit["expected"] != hit["actual"]]
    assert not blocked, blocked
    # The closest foreign form to the selected title exercises the region
    # previously swallowed by one large transparent shape-to-label rectangle.
    label = page.locator(f'.map-node[data-node-id="{primary.id}"] .map-label').bounding_box()
    assert label
    target = min((hit for hit in hits if hit["expected"] != primary.id),
                 key=lambda hit: math.hypot(hit["x"] - label["x"] - label["width"] / 2,
                                            hit["y"] - label["y"] - label["height"] / 2))
    page.mouse.click(target["x"], target["y"])
    expect(page.locator(f'.map-node[data-node-id="{target["expected"]}"]')).to_have_class(re.compile("is-selected"))
    expect(page.locator(f'.map-node[data-node-id="{primary.id}"]')).not_to_have_class(re.compile("is-selected"))
