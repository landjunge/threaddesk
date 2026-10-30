"""Actual multiselection saves and restores its active neighborhood center."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright
from test_graph_view_control_browser import command
from test_pr95_saved_view_filters_review_fix import open_options, snapshot
from test_room_browser import Desk, running

from threaddesk.api.service import ThreadService
from threaddesk.services.graph_view_observation import observe


@pytest.fixture(params=[("json", "svg"), ("sqlite", "svg"), ("json", "sigma"), ("sqlite", "sigma")],
                ids=["json-svg", "sqlite-svg", "json-sigma", "sqlite-sigma"])
def active_center_browser(tmp_path, request):
    storage, renderer = request.param
    desk = Desk(tmp_path / "workspace", storage)
    store = desk.store()
    service = ThreadService(store)
    with store.transaction():
        a = service.create_node("project", "A First center")
        b = service.create_node("task", "B First neighbor")
        d = service.create_node("project", "D Second center")
        e = service.create_node("task", "E Second neighbor")
        other = service.create_node("person", "F Other")
        service.connect(a.id, b.id, "contains")
        service.connect(d.id, e.id, "contains")
        if renderer == "sigma":
            for number in range(123):
                service.create_node("document", f"Z Unrelated {number:03d}")
    if hasattr(store, "connection"):
        store.connection.close()
    with running(desk), sync_playwright() as play:
        browser = play.chromium.launch(executable_path=os.environ.get("THREADDESK_CHROMIUM") or None)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.emulate_media(reduced_motion="reduce")
        page.add_init_script("window.__centerPointerProof=[];addEventListener('pointerdown',event=>window.__centerPointerProof.push({type:'pointerdown',x:event.clientX,y:event.clientY,shift:event.shiftKey,target:event.target.tagName,cls:event.target.className}));")
        page.add_init_script("""addEventListener('threaddesk:graph-view-loaded',event=>{
          const root=event.target, stage=root.querySelector('[data-map-stage]');
          const read=phase=>window.__centerPointerProof.push({type:'view-loaded-layout',phase,
            camera:root.graphController.snapshot().camera,width:stage.clientWidth,height:stage.clientHeight});
          read('before-controls');requestAnimationFrame(()=>requestAnimationFrame(()=>read('after-controls-frames')));
        },true);""")
        errors, acknowledgements = [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda req: acknowledgements.append(req.post_data_json)
                if req.method == "POST" and "/view-control/" in req.url and req.url.endswith("/ack") else None)
        page.goto(desk.url + "/map?lang=en", wait_until="networkidle")
        expect(page.locator("[data-graph-endpoint]")).to_have_attribute("data-renderer", renderer)
        page.locator("[data-map-inspector-toggle]").click()
        page.evaluate("async()=>{await window.ThreadDeskMapViewport.stable(document.querySelector('[data-map-stage]'));await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));}")
        ids = {"a": a.id, "b": b.id, "d": d.id, "e": e.id, "other": other.id}
        try:
            yield page, ids, renderer, acknowledgements
            assert not errors, errors
        finally:
            folder = os.environ.get("THREADDESK_ACTIVE_CENTER_PROOFS")
            if folder:
                destination = Path(folder)
                destination.mkdir(parents=True, exist_ok=True)
                (destination / (request.node.name + ".json")).write_text(json.dumps({
                    "storage": storage, "renderer": renderer, "ids": ids, "snapshot": snapshot(page),
                    "pointer_proof": page.evaluate("window.__centerPointerProof"),
                    "acknowledgements": acknowledgements, "page_errors": errors,
                    "views": [command(page, "graph_view.get", {"id": row["id"]}) for row in command(page, "graph_view.list", {})["views"]],
                    "receipts": [command(page, "graph_view.apply_status", {"operation_id": ack["operation_id"]}) for ack in acknowledgements]}, indent=2) + "\n")
            browser.close()


def click_node(page, identity, *, additive=False):
    root = page.locator("[data-graph-endpoint]")
    if root.get_attribute("data-renderer") == "svg":
        page.locator(f'[data-node-id="{identity}"] .map-node-shape').click(modifiers=["Shift"] if additive else [])
    else:
        point = page.evaluate("id=>document.querySelector('[data-graph-endpoint]').graphController.nodePoint(id)", identity)
        stage = page.locator("[data-map-stage]").bounding_box()
        page.evaluate("row=>window.__centerPointerProof.push(row)", {"type": "planned-node-click", "id": identity, "point": point, "stage": stage, "gpu": page.locator("[data-map-gpu]").bounding_box()})
        if additive:
            # Sigma treats clicks across different nodes within its bundled
            # 300ms doubleClickTimeout as one double-click, not two selections.
            page.wait_for_timeout(310)
            page.keyboard.down("Shift")
        try:
            gpu_box = page.locator("[data-map-gpu]").bounding_box()
            page.mouse.click(gpu_box["x"] + point["x"], gpu_box["y"] + point["y"])
        finally:
            if additive:
                page.keyboard.up("Shift")
    page.evaluate("async()=>{await window.ThreadDeskMapViewport.stable(document.querySelector('[data-map-stage]'));await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));}")


def shown_ids(page):
    page.locator("[data-map-list-toggle]").click()
    identities = set(page.locator("[data-list-node-id]").evaluate_all("ns=>ns.map(n=>n.dataset.listNodeId)"))
    page.locator("[data-map-list-toggle]").click()
    return identities


def apply_and_read(page, identity, operation):
    root = page.locator("[data-graph-endpoint]")
    command(page, "graph_view.apply", {"id": identity, "expected_revision": 1, "operation_id": operation,
        "client_id": root.get_attribute("data-view-client-id")}, mutation=True)
    expect(root).to_have_attribute("data-view-control-operation", operation, timeout=10000)
    expect(root).to_have_attribute("data-view-control-status", "applied")
    result = command(page, "graph_view.apply_status", {"operation_id": operation})["result"]
    assert result["acknowledgement"]["observation"]["matched"]
    return result


@pytest.mark.parametrize("reverse", [False, True], ids=["last-d", "last-a"])
def test_ui_multiselection_save_load_and_apply_keep_actual_active_center(active_center_browser, reverse):
    page, ids, _renderer, acknowledgements = active_center_browser
    order = [ids["d"], ids["a"]] if reverse else [ids["a"], ids["d"]]
    click_node(page, order[0])
    click_node(page, order[1], additive=True)
    assert set(snapshot(page)["selection"]) == set(order)
    open_options(page)
    page.locator("[data-map-hops]").select_option("1")
    expected = {order[-1], ids["b"] if reverse else ids["e"]}
    assert shown_ids(page) == expected
    before = snapshot(page)
    page.locator("[data-map-view-title]").fill("Actual active center")
    page.locator("[data-map-view-save]").click()
    expect(page.locator("[data-map-view]")).not_to_have_value("")
    expect(page.locator("[data-map-view-save]")).to_be_enabled()
    identity = page.locator("[data-map-view]").input_value()
    saved = command(page, "graph_view.get", {"id": identity})["state"]
    page.locator("[data-map-clear-filters]").click()
    page.locator("[data-map-view-load]").click()
    expect(page.locator("[data-map-view-load]")).to_be_enabled()
    expect(page.locator("[data-map-view-message]")).to_be_hidden()
    assert shown_ids(page) == expected
    loaded = snapshot(page)
    for key in ("x", "y", "scale"):
        assert abs(loaded["camera"][key] - saved["camera"][key]) <= 1e-5
    assert loaded["positions"] == saved["positions"]
    assert before["filters"]["center"] == saved["filters"]["center"] == order[-1]
    assert saved["selection"][-1] == order[-1]
    page.locator("[data-map-clear-filters]").click()
    apply_and_read(page, identity, "apply-ui-active-center")
    assert shown_ids(page) == expected
    assert snapshot(page)["selection"][-1] == order[-1]
    expect(page.locator("[data-map-detail-title]")).to_have_text("A First center" if reverse else "D Second center")
    assert page.evaluate("window.__centerPointerProof.filter(row=>row.type==='view-loaded-layout'&&row.phase==='before-controls').length") == 2
    assert snapshot(page)["filters"] == saved["filters"]
    assert acknowledgements[-1]["observed_state"]["filters"] == saved["filters"]
    assert {node["id"] for node in command(page, "graph.query", {"center": order[-1], "hops": 1})["nodes"]} == expected


def test_legacy_multiselection_uses_one_last_entry_fallback(active_center_browser):
    page, ids, _renderer, _acknowledgements = active_center_browser
    state = snapshot(page)
    state.update(selection=[ids["a"], ids["d"]], filters={**state["filters"], "center": "", "hops": 1, "kind": "task"})
    command(page, "graph_view.manage", {"action": "save", "id": "legacy-center", "expected_revision": 0,
        "operation_id": "save-legacy-center", "data": {"title": "Legacy center", "state": state}}, mutation=True)
    apply_and_read(page, "legacy-center", "apply-legacy-center")
    assert shown_ids(page) == {ids["e"]}
    assert snapshot(page)["filters"]["center"] == ids["d"]
    assert snapshot(page)["selection"][-1] == ids["d"]


@pytest.mark.parametrize("case", ["legacy_equal", "wrong_primary", "hops_zero", "empty_selection", "explicit_other", "other_filter"])
def test_effective_center_comparison_is_precise_and_does_not_mutate_input(case):
    import hashlib
    from copy import deepcopy

    from threaddesk.services.graph_views import validate_state

    expected = {"selection": ["first", "last"], "filters": {"center": "", "hops": 1}}
    observed = deepcopy(expected)
    observed["filters"]["center"] = "last"
    if case == "wrong_primary":
        observed["filters"]["center"] = "first"
    elif case == "hops_zero":
        expected["filters"]["hops"] = observed["filters"]["hops"] = 0
    elif case == "empty_selection":
        expected["selection"] = observed["selection"] = []
    elif case == "explicit_other":
        expected["filters"]["center"] = "first"
    elif case == "other_filter":
        observed["filters"]["kind"] = "task"
    original_expected, original_observed = deepcopy(expected), deepcopy(observed)
    result = observe(expected, observed)
    assert result["matched"] == (case == "legacy_equal")
    assert expected == original_expected and observed == original_observed
    assert result["observed_digest"] == hashlib.sha256(json.dumps(validate_state(observed), sort_keys=True, ensure_ascii=False).encode()).hexdigest()
