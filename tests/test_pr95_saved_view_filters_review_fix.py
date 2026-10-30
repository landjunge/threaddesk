"""Saved filter intent survives real browser restoration and its native ACK."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright
from test_graph_view_control_browser import command
from test_room_browser import Desk, running

from threaddesk.api.service import ThreadService


@pytest.fixture(params=["json", "sqlite"])
def saved_filter_browser(tmp_path, request):
    desk = Desk(tmp_path / "workspace", request.param)
    store = desk.store()
    service = ThreadService(store)
    thread = service.create("Saved filter fixture")
    center = service.create_node("project", "A Center", status="active", metadata={"thread_id": thread.id})
    first = service.create_node("task", "B First", status="ready", metadata={"thread_id": thread.id})
    second = service.create_node("document", "C Second", metadata={"thread_id": thread.id})
    other = service.create_node("task", "D Other", status="active")
    absent = service.create_node("project", "Z Off-page project", status="proposed")
    member = service.create_node("task", "Y Off-page member", status="ready", metadata={"project_id": absent.id})
    distant = service.create_node("decision", "X Off-page second")
    service.connect(center.id, first.id, "contains")
    service.connect(first.id, second.id, "depends_on")
    service.connect(absent.id, member.id, "contains")
    service.connect(member.id, distant.id, "contains")
    if hasattr(store, "connection"):
        store.connection.close()
    language = "de" if request.param == "json" else "en"
    identities = {"center": center.id, "first": first.id, "second": second.id,
                  "other": other.id, "off_page": absent.id,
                  "off_page_member": member.id, "off_page_second": distant.id}
    with running(desk), sync_playwright() as play:
        browser = play.chromium.launch(executable_path=os.environ.get("THREADDESK_CHROMIUM") or None)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.emulate_media(reduced_motion="reduce")
        acknowledgements, errors = [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: acknowledgements.append(request.post_data_json)
                if request.method == "POST" and "/view-control/" in request.url and request.url.endswith("/ack") else None)
        page.goto(desk.url + "/map?lang=" + language, wait_until="networkidle")
        expect(page.locator(".map-node")).to_have_count(7)
        try:
            yield page, desk.url, identities, language, acknowledgements
            assert not errors, errors
        finally:
            proof_directory = os.environ.get("THREADDESK_SAVED_FILTER_PROOFS")
            if proof_directory and not page.is_closed():
                folder = Path(proof_directory)
                folder.mkdir(parents=True, exist_ok=True)
                proof = {"storage": request.param, "language": language,
                         "snapshot": snapshot(page), "acknowledgements": acknowledgements,
                         "control_status": page.locator("[data-graph-endpoint]").get_attribute("data-view-control-status"),
                         "visible": sorted(visible_ids(page)), "page_errors": errors}
                (folder / (request.node.name + ".json")).write_text(json.dumps(proof, indent=2) + "\n")
            browser.close()


def snapshot(page):
    return page.evaluate("document.querySelector('[data-graph-endpoint]').graphController.snapshot()")


def visible_ids(page):
    return set(page.locator(".map-node:visible").evaluate_all("nodes => nodes.map(node => node.dataset.nodeId)"))


def apply_saved(page, state, acknowledgements):
    root = page.locator("[data-graph-endpoint]")
    expect(root).to_have_attribute("data-view-client-id", re.compile(".+"))
    command(page, "graph_view.manage", {"action": "save", "id": "saved-filter", "expected_revision": 0,
        "operation_id": "save-filter", "data": {"title": "Saved filter intent", "state": state}}, mutation=True)
    saved = command(page, "graph_view.get", {"id": "saved-filter"})["state"]
    command(page, "graph_view.apply", {"id": "saved-filter", "expected_revision": 1,
        "operation_id": "apply-filter", "client_id": root.get_attribute("data-view-client-id")}, mutation=True)
    expect(root).to_have_attribute("data-view-control-operation", "apply-filter", timeout=10000)
    expect(root).to_have_attribute("data-view-control-status", "applied")
    status = command(page, "graph_view.apply_status", {"operation_id": "apply-filter"})
    assert status["result"]["acknowledgement"]["observation"]["matched"]
    assert acknowledgements and acknowledgements[-1]["operation_id"] == "apply-filter"
    assert acknowledgements[-1]["status"] == "applied"
    assert acknowledgements[-1]["observed_state"]["filters"] == saved["filters"]
    assert snapshot(page)["filters"] == saved["filters"]
    assert snapshot(page)["selection"] == []
    expect(page.locator(".map-node.is-selected")).to_have_count(0)


def open_options(page):
    if not page.locator("[data-map-hops]").is_visible():
        page.locator(".graph-view-tools > summary").click()


@pytest.mark.parametrize(("hops", "previous_selection"), [(1, False), (1, True), (0, True), (2, True)])
def test_explicit_center_is_independent_of_empty_or_previous_selection(saved_filter_browser, hops, previous_selection):
    page, _url, ids, language, acknowledgements = saved_filter_browser
    state = snapshot(page)
    state.update(selection=[], filters={**state["filters"], "center": ids["center"], "hops": hops})
    if previous_selection:
        page.locator(f'[data-node-id="{ids["other"]}"] .map-node-shape').click()
        assert snapshot(page)["selection"] == [ids["other"]]
    apply_saved(page, state, acknowledgements)
    expected = {ids["center"]}
    if hops:
        expected.add(ids["first"])
    if hops == 2:
        expected.add(ids["second"])
    assert visible_ids(page) == expected
    if hops == 0:
        open_options(page)
        expect(page.locator("[data-map-hops]")).to_have_value("center")
        expect(page.locator("[data-map-hops] option:checked")).to_have_text(
            "Nur gespeicherter Mittelpunkt" if language == "de" else "Saved center only")
    page.locator("[data-map-list-toggle]").click()
    assert set(page.locator("[data-list-node-id]").evaluate_all("nodes => nodes.map(node => node.dataset.listNodeId)")) == expected
    page.locator("[data-map-list-toggle]").click()
    open_options(page)
    page.locator("[data-map-hops]").select_option("0")
    expect(page.locator(".map-node:visible")).to_have_count(7)
    assert snapshot(page)["filters"]["center"] == ""
    page.locator("[data-map-clear-filters]").click()
    expect(page.locator(".map-node:visible")).to_have_count(7)
    assert snapshot(page)["filters"]["center"] == ""
    open_options(page)
    # The restored empty selection must not resurrect the previous selection.
    page.locator("[data-map-hops]").select_option("1")
    expect(page.locator(".map-node:visible")).to_have_count(7)
    page.locator(f'[data-node-id="{ids["other"]}"] .map-node-shape').click()
    assert visible_ids(page) == {ids["other"]}
    page.locator("[data-map-clear-filters]").click()
    page.locator("[data-map-kind]").select_option("document")
    assert visible_ids(page) == {ids["second"]}


@pytest.mark.parametrize("missing", ["status", "project", "literal_project"])
def test_saved_filter_without_a_loaded_option_uses_real_filtered_data_and_ack(saved_filter_browser, missing):
    page, url, ids, language, acknowledgements = saved_filter_browser
    if missing == "project":
        # The real project exists beyond the backend's actual first graph page.
        page.route("**/api/graph/v2?*", lambda route: route.continue_(url=route.request.url + "&limit=4"))
        page.goto(url + "/map?lang=" + language, wait_until="networkidle")
        expect(page.locator(".map-node")).to_have_count(4)
    value = "blocked" if missing == "status" else ids["off_page"] if missing == "project" else 'missing-<img src=x>'
    selector = "[data-map-status]" if missing == "status" else "[data-map-project]"
    assert value not in page.locator(selector + " option").evaluate_all("options => options.map(option => option.value)")
    state = snapshot(page)
    state.update(selection=[], filters={**state["filters"], "status" if missing == "status" else "project_id": value})
    page.locator(f'[data-node-id="{ids["other"]}"] .map-node-shape').click()
    apply_saved(page, state, acknowledgements)
    expected = {ids["off_page"], ids["off_page_member"], ids["off_page_second"]} if missing == "project" else set()
    assert visible_ids(page) == expected
    expect(page.locator(selector)).to_have_value(value)
    option = page.locator(selector + " option:checked")
    assert option.locator("*").count() == 0
    if missing == "status":
        expect(option).to_have_text("Blockiert" if language == "de" else "Blocked")
    elif missing == "project":
        expect(option).to_have_text("Z Off-page project")
    else:
        expect(option).to_have_text(("Projekt" if language == "de" else "Project") + ": " + value)
    page.locator("[data-map-list-toggle]").click()
    assert set(page.locator("[data-list-node-id]").evaluate_all("nodes => nodes.map(node => node.dataset.listNodeId)")) == expected
    page.locator("[data-map-list-toggle]").click()
    page.locator("[data-map-clear-filters]").click()
    expect(page.locator(".map-node:visible")).to_have_count(4 if missing == "project" else 7)
    assert snapshot(page)["filters"]["status"] == snapshot(page)["filters"]["project_id"] == ""


def test_paged_filters_keep_explicit_center_until_clear_then_use_current_selection(saved_filter_browser):
    page, url, ids, language, acknowledgements = saved_filter_browser
    page.route("**/api/graph/v2?*", lambda route: route.continue_(url=route.request.url + "&limit=4"))
    page.goto(url + "/map?lang=" + language, wait_until="networkidle")
    expect(page.locator(".map-node")).to_have_count(4)
    state = snapshot(page)
    state.update(selection=[], filters={**state["filters"], "center": ids["center"], "hops": 1})
    page.locator(f'[data-node-id="{ids["other"]}"] .map-node-shape').click()
    apply_saved(page, state, acknowledgements)
    assert visible_ids(page) == {ids["center"], ids["first"]}
    page.locator(f'[data-node-id="{ids["first"]}"] .map-node-shape').click()
    open_options(page)
    with page.expect_response(lambda response: "/api/graph/v2?" in response.url
                              and response.request.method == "GET") as refreshed:
        page.locator("[data-map-mode]").select_option("modified")
    assert refreshed.value.ok
    assert parse_qs(urlsplit(refreshed.value.url).query)["center"] == [ids["center"]]
    expect(page.locator(".map-node:visible")).to_have_count(2)
    assert visible_ids(page) == {ids["center"], ids["first"]}
    with page.expect_response(lambda response: "/api/graph/v2?" in response.url
                              and response.request.method == "GET") as cleared:
        page.locator("[data-map-clear-filters]").click()
    assert cleared.value.ok
    assert "center" not in parse_qs(urlsplit(cleared.value.url).query, keep_blank_values=True)
    expect(page.locator(".map-node:visible")).to_have_count(4)
    assert snapshot(page)["filters"]["center"] == ""
    with page.expect_response(lambda response: "/api/graph/v2?" in response.url
                              and response.request.method == "GET") as selected:
        page.locator("[data-map-hops]").select_option("1")
    assert selected.value.ok
    assert parse_qs(urlsplit(selected.value.url).query)["center"] == [ids["first"]]
    expect(page.locator(".map-node:visible")).to_have_count(3)
    assert visible_ids(page) == {ids["center"], ids["first"], ids["second"]}


@pytest.mark.parametrize("hops", [0, 1, 2])
def test_off_page_center_hydrates_its_actual_bounded_neighborhood(saved_filter_browser, hops):
    page, url, ids, language, acknowledgements = saved_filter_browser
    page.route("**/api/graph/v2?*", lambda route: route.continue_(url=route.request.url + "&limit=4"))
    page.goto(url + "/map?lang=" + language, wait_until="networkidle")
    expect(page.locator(".map-node")).to_have_count(4)
    assert ids["off_page"] not in visible_ids(page)
    state = snapshot(page)
    original_positions = state["positions"]
    state.update(selection=[], filters={**state["filters"], "center": ids["off_page"], "hops": hops})
    with page.expect_response(lambda response: response.request.method == "POST"
                              and response.url.endswith("/api/graph/v2")
                              and response.request.post_data_json.get("center") == ids["off_page"]) as filtered:
        apply_saved(page, state, acknowledgements)
    assert filtered.value.ok
    expected = {ids["off_page"]}
    if hops:
        expected.add(ids["off_page_member"])
    if hops == 2:
        expected.add(ids["off_page_second"])
    assert {node["id"] for node in filtered.value.json()["nodes"]} == expected
    assert visible_ids(page) == expected
    restored_positions = snapshot(page)["positions"]
    assert all(restored_positions[identity] == point for identity, point in original_positions.items())
    open_options(page)
    page.locator("[data-map-hops]").select_option("0")
    expect(page.locator(".map-node:visible")).to_have_count(4)
    assert snapshot(page)["filters"]["center"] == ""


def test_unknown_center_is_an_empty_filter_not_a_required_saved_node(saved_filter_browser):
    page, _url, _ids, language, acknowledgements = saved_filter_browser
    state = snapshot(page)
    state.update(selection=[], filters={**state["filters"], "center": "absent-center", "hops": 1})
    apply_saved(page, state, acknowledgements)
    assert visible_ids(page) == set()
    expect(page.locator("[data-map-empty]")).to_have_text(
        "Keine Knoten passen zu diesen Filtern." if language == "de" else "No nodes match these filters.")
    page.locator("[data-map-clear-filters]").click()
    expect(page.locator(".map-node:visible")).to_have_count(7)


@pytest.mark.parametrize("context", ["center", "project"])
def test_combined_filters_hydrate_structural_nodes_hidden_by_the_predicate(saved_filter_browser, context):
    page, url, ids, language, acknowledgements = saved_filter_browser
    page.route("**/api/graph/v2?*", lambda route: route.continue_(url=route.request.url + "&limit=4"))
    page.goto(url + "/map?lang=" + language, wait_until="networkidle")
    expect(page.locator(".map-node")).to_have_count(4)
    state = snapshot(page)
    filters = {**state["filters"], "kind": "decision"}
    if context == "center":
        filters.update(center=ids["off_page"], hops=2)
    else:
        filters.update(project_id=ids["off_page"])
    state.update(selection=[], filters=filters)
    with page.expect_response(lambda response: response.request.method == "POST"
                              and response.url.endswith("/api/graph/v2")
                              and response.request.post_data_json.get("kind") == "decision") as filtered:
        apply_saved(page, state, acknowledgements)
    assert filtered.value.ok
    expected = {ids["off_page_second"]}
    assert {node["id"] for node in filtered.value.json()["nodes"]} == expected
    assert visible_ids(page) == expected


@pytest.mark.parametrize("incomplete", ["next_offset", "relations_truncated"])
def test_incomplete_filter_context_reports_real_failed_ack(saved_filter_browser, incomplete):
    page, _url, ids, _language, acknowledgements = saved_filter_browser
    state = snapshot(page)
    state.update(selection=[], filters={**state["filters"], "center": ids["off_page"], "hops": 1})

    def incomplete_read(route):
        if route.request.method == "POST" and route.request.post_data_json.get("center") == ids["off_page"]:
            response = route.fetch()
            assert response.ok
            document = response.json()
            document[incomplete] = 1000 if incomplete == "next_offset" else True
            route.fulfill(response=response, json=document)
        else:
            route.continue_()

    # Only corrupt the read envelope. The app itself sends its real failed ACK.
    page.route("**/api/graph/v2", incomplete_read)
    root = page.locator("[data-graph-endpoint]")
    expect(root).to_have_attribute("data-view-client-id", re.compile(".+"))
    command(page, "graph_view.manage", {"action": "save", "id": "saved-filter", "expected_revision": 0,
        "operation_id": "save-filter", "data": {"title": "Incomplete context", "state": state}}, mutation=True)
    command(page, "graph_view.apply", {"id": "saved-filter", "expected_revision": 1,
        "operation_id": "apply-filter", "client_id": root.get_attribute("data-view-client-id")}, mutation=True)
    expect(root).to_have_attribute("data-view-control-operation", "apply-filter", timeout=10000)
    expect(root).to_have_attribute("data-view-control-status", "failed")
    status = command(page, "graph_view.apply_status", {"operation_id": "apply-filter"})
    assert status["result"]["acknowledgement"]["error_code"] == "view_graph_limit"
    assert acknowledgements[-1]["status"] == "failed"
    assert acknowledgements[-1]["error_code"] == "view_graph_limit"
