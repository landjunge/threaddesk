"""Real server/browser activity modes, DOM parity and durable graph views."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os

import pytest
from playwright.sync_api import expect, sync_playwright

from test_desk_browser import Desk
from threaddesk.api.service import ThreadService
from threaddesk.services.activity import ActivityService
from threaddesk.services.library_batch import LibraryBatchImporter
from threaddesk.storage.json_store import JsonStore


@pytest.fixture(params=["de", "en"])
def graph_activity(tmp_path, request):
    home = tmp_path / "workspace"
    store = JsonStore(home)
    svc = ThreadService(store=store)
    thread = svc.create("Activity project")
    project = svc.create_node("project", "Activity project", metadata={"thread_id": thread.id})
    other = svc.create_node("task", "Unrelated task")
    source = tmp_path / "originals";source.mkdir()
    (source / "Recent.txt").write_text("Recent file content")
    importer = LibraryBatchImporter(store)
    imported = importer.run(importer.manifest_for_folder(source.resolve(), thread_id=thread.id, node_id=project.id), operation_id="activity-fixture")
    identity = imported["files"][0]["record_id"]
    now = datetime.now(timezone.utc)
    # Synthetic completion evidence is fixture data, not an OS launch claim.
    record = importer.importer._record_by_id(identity)
    activity = ActivityService(store)
    activity.record_open_receipt({"action": "open", "status": "launch_requested", "operation_id": "fixture-open",
                                  "record_id": identity, "sha256": record["sha256"],
                                  "launch_requested_at": (now - timedelta(hours=1)).isoformat()})
    activity.record_content_change(record, {"id": "old-fixture", "sha256": "a" * 64},
                                   source_modified_at=(now - timedelta(days=10)).isoformat(), operation_id="fixture-change")
    desk = Desk(home);url = desk.start()
    try:
        with sync_playwright() as play:
            browser = play.chromium.launch(executable_path=os.environ.get("THREADDESK_CHROMIUM") or None)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.emulate_media(reduced_motion="reduce")
            errors = [];page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(url + "/map?lang=" + request.param, wait_until="networkidle")
            expect(page.locator(".map-node")).to_have_count(3)
            yield page, url, project.id, identity, other.id, request.param
            assert not errors, errors
            browser.close()
    finally:
        desk.stop()


def test_time_modes_and_list_selection_share_the_inspector(graph_activity):
    page, _url, project, identity, other, language = graph_activity
    root = page.locator("[data-graph-endpoint]")
    expect(root).to_have_attribute("data-color-mode", "work")
    expect(page.locator(f'[data-node-id="{identity}"]')).to_have_attribute("data-age-band", "24h")
    expect(page.locator(f'[data-node-id="{other}"]')).to_have_attribute("data-age-band", "unknown")
    initial = page.locator("[data-map-stage]").bounding_box()
    page.locator(".graph-view-tools > summary").click()
    page.locator("[data-map-mode]").select_option("modified")
    expect(page.locator(f'[data-node-id="{identity}"]')).to_have_attribute("data-age-band", "30d")
    page.locator("[data-map-age]").select_option("30d")
    expect(page.locator(f'[data-node-id="{other}"]')).to_be_hidden()
    page.locator(".graph-view-tools > summary").click()
    after = page.locator("[data-map-stage]").bounding_box()
    assert abs(initial["height"] - after["height"]) <= 32, (initial, after)
    assert after["height"] > 450
    page.locator("[data-map-list-toggle]").click()
    expect(page.locator(f'[data-list-node-id="{identity}"]')).to_be_visible()
    expect(page.locator(f'[data-list-node-id="{other}"]')).to_have_count(0)
    page.locator(f'[data-list-node-id="{identity}"]').focus()
    page.keyboard.press("Enter")
    expect(page.locator("[data-map-detail-title]")).to_have_text("Recent.txt")
    expect(page.locator("[data-map-detail-activity]")).to_contain_text("Recent.txt")
    expect(page.locator("[data-map-inspector]")).to_be_visible()


def test_saved_camera_positions_filters_and_fixed_state_survive_reload(graph_activity):
    page, url, project, identity, other, language = graph_activity
    page.locator(f'[data-node-id="{project}"] .map-node-shape').click()
    page.locator('[data-map-tab="selection"]').click()
    page.locator("[data-map-fix-selected]").click()
    page.locator("[data-map-zoom-in]").click()
    before = page.evaluate("document.querySelector('[data-graph-endpoint]').graphController.snapshot()")
    page.locator(".graph-view-tools > summary").click()
    page.locator("[data-map-view-title]").fill("Saved working view")
    with page.expect_response(lambda response: response.url.endswith("/api/graph/views") and response.request.method == "POST") as observed:
        page.locator("[data-map-view-save]").click()
    assert observed.value.ok, observed.value.text()
    expect(page.locator("[data-map-view-message]")).to_have_text("Ansicht gespeichert." if language == "de" else "View saved.")
    identity = page.locator("[data-map-view]").input_value()
    assert identity
    page.reload(wait_until="networkidle")
    page.locator(".graph-view-tools > summary").click()
    page.locator("[data-map-view]").select_option(identity)
    page.locator("[data-map-view-load]").click()
    expect(page.locator(f'[data-node-id="{project}"]')).to_have_attribute("data-fixed", "true")
    after = page.evaluate("document.querySelector('[data-graph-endpoint]').graphController.snapshot()")
    assert after["camera"] == before["camera"]
    assert after["positions"] == before["positions"]
    assert after["filters"] == before["filters"]


def test_uncertain_saved_view_reuses_exact_operation_and_readback(graph_activity):
    page, _url, _project, _identity, _other, language = graph_activity
    page.locator(".graph-view-tools > summary").click()
    page.locator("[data-map-view-title]").fill("Save with lost response")
    requests = []
    def lose_response(route):
        if route.request.method == "POST":
            requests.append(route.request.post_data_json)
            if len(requests) == 1:
                response = route.fetch()
                assert response.ok
                route.abort("failed")
                return
        route.continue_()
    page.route("**/api/graph/views", lose_response)
    page.locator("[data-map-view-save]").click()
    expect(page.locator("[data-map-view-message]")).to_have_text(
        "Ansicht konnte nicht bestätigt werden. Eingabe bleibt erhalten." if language == "de" else
        "View could not be confirmed. Your input is preserved.")
    page.locator("[data-map-view-save]").click()
    expect(page.locator("[data-map-view-message]")).to_have_text("Ansicht gespeichert." if language == "de" else "View saved.")
    assert len(requests) == 2 and requests[0] == requests[1]
    result = page.request.get(_url + "/api/graph/views").json()
    assert result["total"] == 1 and result["views"][0]["revision"] == 1
