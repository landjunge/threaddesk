"""Actual bilingual trash controls preserve originals, identities and history."""
from __future__ import annotations

import hashlib
import os

import pytest
from playwright.sync_api import expect, sync_playwright

from http_ui_client import choose_language
from test_desk_browser import Desk, _open_section
from threaddesk.api.service import ThreadService
from threaddesk.services.library_api import LibraryApplication
from threaddesk.storage.json_store import JsonStore


@pytest.fixture
def trash_desk(tmp_path):
    home = tmp_path / "workspace"
    svc = ThreadService(JsonStore(home))
    thread = svc.create("TrashThreadNeedle")
    svc.set_note("Original notes survive trash", thread.id)
    entry = svc.append_whiteboard(thread.id, actor="QA operator", actor_type="human",
                                 entry_type="note", content="Whiteboard history retained")
    snapshot = svc.snapshot("Before trash", thread.id)
    project = svc.create_node("project", thread.title, metadata={"thread_id": thread.id})
    child = svc.create_node("task", "Linked retained task", metadata={"thread_id": thread.id})
    edge = svc.connect(project.id, child.id, "contains")
    folder = tmp_path / "originals"
    folder.mkdir()
    original = folder / "retain-original.txt"
    original.write_text("AttachmentReadbackNeedle original bytes", encoding="utf-8")
    imported = LibraryApplication(svc.store).call({"action": "import", "operation_id": "fixture-import",
                                                 "data": {"source": str(folder), "thread_id": thread.id}})
    assert imported["complete"]
    record_id = imported["files"][0]["record_id"]
    desk = Desk(home)
    url = desk.start()
    try:
        with sync_playwright() as play:
            browser = play.chromium.launch(executable_path=os.environ.get("THREADDESK_CHROMIUM") or None)
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            opens = []
            def reject_unexpected_open(route):
                body = route.request.post_data_json or {}
                args = body.get("arguments", body)
                if args.get("action") == "open":
                    opens.append(body)
                    route.abort()
                else:
                    route.continue_()
            page.route("**/api/library/command", reject_unexpected_open)
            page.route("**/api/commands", reject_unexpected_open)
            page.on("dialog", lambda dialog: dialog.accept())
            yield {"page": page, "url": url, "svc": svc, "thread": thread.id,
                   "project": project.id, "child": child.id, "edge": edge.id,
                   "entry": entry["entry"]["id"], "snapshot": snapshot.id,
                   "record": record_id, "original": original,
                   "sha256": hashlib.sha256(original.read_bytes()).hexdigest(), "opens": opens}
            browser.close()
    finally:
        desk.stop()


def command(page, identity, arguments=None):
    value = page.evaluate("""async ({command, arguments: args}) => {
      const catalog = await (await fetch('/api/commands/catalog?limit=1')).json();
      const response = await window.threadDeskWrite('/api/commands', {
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({version:1,workspace_id:catalog.workspace_id,command,arguments:args})});
      return {status:response.status,body:await response.json()};
    }""", {"command": identity, "arguments": arguments or {}})
    assert value["status"] == 200 and value["body"]["ok"], value
    return value["body"]["result"]


def graph(page):
    return page.evaluate("async()=>await(await fetch('/api/graph',{cache:'no-store'})).json()")


@pytest.mark.parametrize("language", ["de", "en"])
def test_thread_trash_control_hides_and_restores_original_ids_history_and_attachments(trash_desk, language):
    d = trash_desk
    page, url = d["page"], d["url"]
    choose_language(page, url, language)
    expect(page.locator("h1")).to_have_text("TrashThreadNeedle")
    assert any(hit["thread_id"] == d["thread"] for hit in command(page, "library_query", {
        "action": "search", "query": "TrashThreadNeedle", "entity_type": "thread"})["hits"])
    _open_section(page, "thread-edit")
    page.locator(f'[data-trash-object="{d["thread"]}"]').click()
    expect(page).to_have_url(url + "/trash")
    removed = page.locator("[data-trash-items] > li").filter(has_text="TrashThreadNeedle")
    expect(removed).to_have_count(1)
    normal = command(page, "list_threads")
    assert d["thread"] not in {row["id"] for row in normal}
    hidden_graph = graph(page)
    assert not {d["project"], d["child"], d["record"]} & {node["id"] for node in hidden_graph["nodes"]}
    assert d["edge"] not in {edge["id"] for edge in hidden_graph["relations"]}
    assert not command(page, "library_query", {"action": "search", "query": "TrashThreadNeedle", "entity_type": "thread"})["hits"]
    assert hashlib.sha256(d["original"].read_bytes()).hexdigest() == d["sha256"]
    removed.get_by_role("button", name="Wiederherstellen" if language == "de" else "Restore", exact=True).click()
    expect(removed).to_have_count(0)
    expect(page.locator("[data-trash-message]")).to_contain_text("Wiederhergestellt" if language == "de" else "Restored")
    restored = command(page, "get_thread", {"id": d["thread"]})
    assert restored["id"] == d["thread"] and "Original notes survive trash" in restored["notes"]
    assert {row["id"] for row in command(page, "list_snapshots", {"id": d["thread"]})} == {d["snapshot"]}
    assert [row["id"] for row in command(page, "whiteboard.list", {"id": d["thread"]})["items"]] == [d["entry"]]
    restored_graph = graph(page)
    assert {d["project"], d["child"], d["record"]} <= {node["id"] for node in restored_graph["nodes"]}
    assert d["edge"] in {edge["id"] for edge in restored_graph["relations"]}
    assert command(page, "library_query", {"action": "info", "id": d["record"]})["id"] == d["record"]
    assert any(hit["thread_id"] == d["thread"] for hit in command(page, "library_query", {
        "action": "search", "query": "TrashThreadNeedle", "entity_type": "thread"})["hits"])
    page.goto(url + "/?thread=" + d["thread"], wait_until="networkidle")
    expect(page.locator("h1")).to_have_text("TrashThreadNeedle")
    expect(page.locator(".whiteboard-body")).to_have_text("Whiteboard history retained")
    assert not d["opens"]


@pytest.mark.parametrize("language", ["de", "en"])
def test_file_tab_restores_record_and_search_without_external_open(trash_desk, language):
    d = trash_desk
    page, url = d["page"], d["url"]
    choose_language(page, url, language)
    page.goto(url + "/map", wait_until="networkidle")
    page.locator(f'.map-node[data-node-id="{d["project"]}"] .map-node-shape').click()
    panel = page.locator("[data-graph-files]")
    panel.locator(f'[data-file-record="{d["record"]}"]').click()
    expect(panel.locator("[data-file-preview]")).to_be_visible()
    expect(panel.locator("[data-file-body]")).to_contain_text("AttachmentReadbackNeedle")
    panel.locator('[data-file-action="trash"]').click()
    expect(panel.locator(f'[data-file-record="{d["record"]}"]')).to_have_count(0)
    assert d["record"] not in {node["id"] for node in graph(page)["nodes"]}
    assert not command(page, "library_query", {"action": "search", "query": "AttachmentReadbackNeedle"})["hits"]
    page.goto(url + "/trash", wait_until="networkidle")
    page.locator('[data-trash-tab="files"]').click()
    row = page.locator("[data-trash-items] > li").filter(has_text="retain-original.txt")
    expect(row).to_have_count(1)
    row.get_by_role("button", name="Wiederherstellen" if language == "de" else "Restore", exact=True).click()
    expect(row).to_have_count(0)
    restored = command(page, "library_query", {"action": "info", "id": d["record"]})
    assert restored["id"] == d["record"] and restored["thread_id"] == d["thread"] and not restored["trashed"]
    assert any(hit.get("record_id") == d["record"] for hit in command(page, "library_query", {
        "action": "search", "query": "AttachmentReadbackNeedle"})["hits"])
    assert d["record"] in {node["id"] for node in graph(page)["nodes"]}
    assert hashlib.sha256(d["original"].read_bytes()).hexdigest() == d["sha256"]
    assert not d["opens"]
