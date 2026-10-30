"""Real live invalidation retains the structural context of saved filters."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from playwright.sync_api import expect
from test_graph_view_control_browser import command
from test_pr95_saved_view_filters_review_fix import apply_saved, snapshot, visible_ids

pytest_plugins = ("test_pr95_saved_view_filters_review_fix",)
ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("scope", ["center_kind", "center_status", "project_kind", "combined", "pure_center", "pure_project"])
def test_real_live_refresh_retains_center_and_project_context(saved_filter_browser, tmp_path, scope):
    page, url, ids, language, acknowledgements = saved_filter_browser
    root = page.locator("[data-graph-endpoint]")
    expect(root).to_have_attribute("data-live-status", "ready")
    state = snapshot(page)
    filters = {**state["filters"]}
    if scope.startswith("center") or scope == "pure_center":
        filters.update(center=ids["center"], hops=1)
        if scope == "center_kind":
            filters.update(kind="task")
        elif scope == "center_status":
            filters.update(status="ready")
    else:
        filters.update(project_id=ids["off_page"])
        if scope != "pure_project":
            filters.update(kind="decision")
        if scope == "combined":
            filters.update(center=ids["off_page"], hops=2)
    state.update(selection=[], filters=filters)
    assert "node_ids" not in state["filters"]
    apply_saved(page, state, acknowledgements)
    expected = {ids["first"]} if scope.startswith("center") else {ids["off_page_second"]}
    if scope == "pure_center":
        expected = {ids["center"], ids["first"]}
    elif scope == "pure_project":
        expected = {ids["off_page"], ids["off_page_member"], ids["off_page_second"]}
    assert visible_ids(page) == expected
    before = snapshot(page)
    loaded, live = [], []
    page.on("response", lambda response: loaded.append({"url": response.url, "method": response.request.method})
            if "/api/graph/v2" in response.url else None)
    page.on("request", lambda request: live.append(request.url)
            if request.url.endswith("/api/graph/change-status") else None)
    page.evaluate("""() => {
      const root=document.querySelector('[data-graph-endpoint]');
      root.dataset.testLiveUpdates='0';
      root.addEventListener('threaddesk:graph-live-updated',()=>{
        root.dataset.testLiveUpdates=String(Number(root.dataset.testLiveUpdates)+1);
      });
    }""")
    # A separate real CLI writer invalidates the backend fingerprint. No JS
    # refresh or ACK is injected; the production live poll drives the redraw.
    request = {"version": 1, "workspace_id": page.request.get(url + "/api/commands/catalog").json()["workspace_id"],
               "command": "graph.node.create", "arguments": {"kind": "person", "title": "Unrelated live change"},
               "operation_id": "external-refresh-context", "expected_revision": 0}
    path = tmp_path / "external-refresh.json"
    path.write_text(json.dumps(request))
    environment = {**os.environ, "THREADDESK_HOME": str(tmp_path / "workspace"),
                   "THREADDESK_STORAGE": "json" if language == "de" else "sqlite", "PYTHONPATH": str(ROOT / "src")}
    done = subprocess.run([sys.executable, "-m", "threaddesk.ui.cli", "command", "--request-file", str(path)],
                          cwd=ROOT, env=environment, capture_output=True, text=True, timeout=30, check=False)
    assert done.returncode == 0, done.stdout + done.stderr
    assert json.loads(done.stdout)["ok"]
    canonical = command(page, "graph.query", {})["nodes"]
    backend = command(page, "graph.query", {key: value for key, value in filters.items() if key != "center" or value})
    assert {node["id"] for node in backend["nodes"]} == expected
    expect(root).to_have_attribute("data-test-live-updates", "1", timeout=20000)
    expect(root).to_have_attribute("data-live-status", "ready")
    assert live and loaded
    if scope.startswith("pure"):
        assert all(response["method"] == "GET" for response in loaded), loaded
    else:
        assert all(response["method"] == "POST" for response in loaded), loaded
    assert visible_ids(page) == expected
    after = snapshot(page)
    assert after["filters"] == before["filters"]
    assert after["camera"] == before["camera"]
    assert after["selection"] == before["selection"]
    for identity in expected:
        assert after["positions"][identity] == before["positions"][identity]
    assert command(page, "graph.query", {})["nodes"] == canonical
