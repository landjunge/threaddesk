"""Exact saved ID filters use real graph reads and the browser's native ACK."""
from __future__ import annotations

import pytest
from playwright.sync_api import expect
from test_graph_view_control_browser import command
from test_pr95_saved_view_filters_review_fix import (
    apply_saved,
    open_options,
    snapshot,
    visible_ids,
)

pytest_plugins = ("test_pr95_saved_view_filters_review_fix",)


@pytest.mark.parametrize("scope", ["onpage", "offpage", "center", "project"])
def test_exact_ids_survive_restore_context_and_manual_filters(saved_filter_browser, scope):
    page, url, ids, language, acknowledgements = saved_filter_browser
    if scope != "onpage":
        page.route("**/api/graph/v2?*", lambda route: route.continue_(url=route.request.url + "&limit=4"))
        page.goto(url + "/map?lang=" + language, wait_until="networkidle")
        expect(page.locator(".map-node")).to_have_count(4)
    target = ids["second"] if scope == "onpage" else ids["off_page_second"]
    exact = [target, target]
    state = snapshot(page)
    filters = {**state["filters"], "node_ids": exact}
    if scope == "center":
        filters.update(center=ids["off_page"], hops=2)
    if scope == "project":
        filters.update(project_id=ids["off_page"])
    state.update(selection=[], filters=filters)
    apply_saved(page, state, acknowledgements)
    assert visible_ids(page) == {target}
    page.evaluate("document.querySelector('[data-graph-endpoint]').graphController.snapshot().filters.node_ids.push('snapshot-only')")
    assert snapshot(page)["filters"]["node_ids"] == exact
    page.locator("[data-map-list-toggle]").click()
    assert page.locator("[data-list-node-id]").evaluate_all("ns=>ns.map(n=>n.dataset.listNodeId)") == [target]
    page.locator("[data-map-list-toggle]").click()
    open_options(page)
    with page.expect_response(lambda r: "/api/graph/v2" in r.url and r.request.method == "POST") as response:
        page.locator("[data-map-status]").select_option("idea")
    assert response.value.ok
    assert response.value.request.post_data_json["node_ids"] == [target]
    expect(page.locator(".map-node:visible")).to_have_count(1)
    assert snapshot(page)["filters"]["node_ids"] == exact
    with page.expect_response(lambda r: "/api/graph/v2?" in r.url and r.request.method == "GET") as cleared:
        page.locator("[data-map-clear-filters]").click()
    assert cleared.value.ok and "node_ids" not in cleared.value.url
    expect(page.locator(".map-node:visible")).to_have_count(7 if scope == "onpage" else 4)
    assert "node_ids" not in snapshot(page)["filters"]


@pytest.mark.parametrize("empty_positions", [False, True])
def test_unknown_exact_id_is_authoritatively_empty_and_optional_field_can_be_removed(saved_filter_browser, empty_positions):
    page, _url, _ids, _language, acknowledgements = saved_filter_browser
    state = snapshot(page)
    state.update(selection=[], filters={**state["filters"], "node_ids": ["valid_unknown_id"]})
    if empty_positions:
        state["positions"] = {}
    apply_saved(page, state, acknowledgements)
    assert visible_ids(page) == set()
    root = page.locator("[data-graph-endpoint]")
    state["filters"].pop("node_ids")
    command(page, "graph_view.manage", {"action": "save", "id": "unrestricted", "expected_revision": 0,
        "operation_id": "save-unrestricted", "data": {"title": "Unrestricted", "state": state}}, mutation=True)
    command(page, "graph_view.apply", {"id": "unrestricted", "expected_revision": 1,
        "operation_id": "apply-unrestricted", "client_id": root.get_attribute("data-view-client-id")}, mutation=True)
    expect(root).to_have_attribute("data-view-control-operation", "apply-unrestricted", timeout=10000)
    expect(root).to_have_attribute("data-view-control-status", "applied")
    assert "node_ids" not in snapshot(page)["filters"]
    assert command(page, "graph_view.apply_status", {"operation_id": "apply-unrestricted"})["result"]["acknowledgement"]["observation"]["matched"]
    assert visible_ids(page) == {node["id"] for node in command(page, "graph.query", {})["nodes"]}


def test_empty_saved_ids_rejected_and_unqueryable_saved_ids_fail_without_false_apply(saved_filter_browser):
    page, _url, _ids, _language, acknowledgements = saved_filter_browser
    state = snapshot(page)
    state.update(selection=[], filters={**state["filters"], "node_ids": []})
    rejected = page.evaluate("""async state => {
      const c=await(await fetch('/api/commands/catalog')).json();
      const args={action:'save',id:'empty-ids',expected_revision:0,operation_id:'save-empty-ids',data:{title:'Empty',state}};
      const response=await window.threadDeskWrite('/api/commands',{headers:{'Content-Type':'application/json'},body:JSON.stringify(
        {version:1,workspace_id:c.workspace_id,command:'graph_view.manage',arguments:args,operation_id:args.operation_id,expected_revision:0})});
      return {status:response.status,body:await response.json()};
    }""", state)
    assert rejected["status"] == 400, rejected
    assert acknowledgements == []
    state["filters"]["node_ids"] = ["bad:syntax"]
    command(page, "graph_view.manage", {"action": "save", "id": "unqueryable", "expected_revision": 0,
        "operation_id": "save-unqueryable", "data": {"title": "Unqueryable", "state": state}}, mutation=True)
    assert command(page, "graph_view.get", {"id": "unqueryable"})["state"]["filters"]["node_ids"] == ["bad:syntax"]
    root = page.locator("[data-graph-endpoint]")
    before = snapshot(page)
    command(page, "graph_view.apply", {"id": "unqueryable", "expected_revision": 1,
        "operation_id": "apply-unqueryable", "client_id": root.get_attribute("data-view-client-id")}, mutation=True)
    expect(root).to_have_attribute("data-view-control-operation", "apply-unqueryable", timeout=10000)
    expect(root).to_have_attribute("data-view-control-status", "failed")
    result = command(page, "graph_view.apply_status", {"operation_id": "apply-unqueryable"})["result"]
    assert result["acknowledgement"]["error_code"] == "view_graph_unavailable"
    assert result["acknowledgement"]["observation"] is None
    assert snapshot(page) == before


def test_exact_ids_with_german_query_match_actual_backend(saved_filter_browser):
    page, url, _ids, language, acknowledgements = saved_filter_browser
    created = page.evaluate("""async () => {
      const c=await(await fetch('/api/commands/catalog')).json();
      const r=await window.threadDeskWrite('/api/commands',{headers:{'Content-Type':'application/json'},body:JSON.stringify(
        {version:1,workspace_id:c.workspace_id,command:'graph.node.create',arguments:{kind:'task',title:'Müller Straße'},
         operation_id:'create-german',expected_revision:0})});
      return {status:r.status,body:await r.json()};
    }""")
    assert created["status"] == 200, created
    node = created["body"]["result"]
    page.goto(url + "/map?lang=" + language, wait_until="networkidle")
    expect(page.locator(".map-node")).to_have_count(8)
    arguments = {"node_ids": [node["id"]], "query": "mueller strasse"}
    assert [n["id"] for n in command(page, "graph.query", arguments)["nodes"]] == [node["id"]]
    state = snapshot(page)
    state.update(selection=[], filters={**state["filters"], **arguments})
    apply_saved(page, state, acknowledgements)
    assert visible_ids(page) == {node["id"]}
