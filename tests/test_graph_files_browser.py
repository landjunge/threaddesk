"""Real graph file-manager behaviour against the existing isolated server fixture."""
from __future__ import annotations

import os

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect, sync_playwright
from http_ui_client import choose_language
from test_desk_browser import Desk
from threaddesk.api.service import ThreadService
from threaddesk.storage.json_store import JsonStore


@pytest.fixture
def graph_files(tmp_path):
    home = tmp_path / "workspace"
    svc = ThreadService(store=JsonStore(home))
    thread = svc.create("Library Project")
    node = svc.create_node("project", "Library Project", metadata={"thread_id": thread.id})
    svc.create_node("task", "Supporting task", metadata={"thread_id": thread.id})
    source = tmp_path / "originals"
    source.mkdir()
    original = source / "fixture.txt"
    original.write_text("Unique content marker library-owl", encoding="utf-8")
    desk = Desk(home)
    url = desk.start()
    try:
        with sync_playwright() as play:
            browser = play.chromium.launch(executable_path=os.environ.get("THREADDESK_CHROMIUM"))
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.goto(url + "/map", wait_until="networkidle")
            yield page, url, home, source, original, thread.id, node.id
            browser.close()
    finally:
        desk.stop()


def command(page, arguments):
    result = page.evaluate("""async args => {
      const response = await window.threadDeskWrite('/api/library/command', {
        method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(args)});
      return await response.json();
    }""", arguments)
    assert result["ok"], result
    return result["result"]


def read(page, action, **arguments):
    return page.evaluate("""async args => {
      const response=await fetch('/api/library/query?'+new URLSearchParams(args));
      return (await response.json()).result;
    }""", {"action": action, **arguments})


def submit_search(page, panel):
    from urllib.parse import parse_qs, urlsplit
    with page.expect_response(lambda response: "/api/library/query?" in response.url
                              and parse_qs(urlsplit(response.url).query).get("action") == ["search"]) as observed:
        panel.locator('[data-file-search] button[type="submit"]').click()
    payload = observed.value.json()
    assert payload["ok"], payload
    return payload["result"]


def imported(graph_files):
    page, url, home, source, original, thread, node = graph_files
    result = command(page, {"action": "import", "operation_id": "browser-import",
                            "data": {"source": str(source), "thread_id": thread}})
    assert result["complete"], result
    command(page, {"action": "reindex", "operation_id": "browser-index"})
    record = read(page, "list")["records"][0]
    page.reload(wait_until="networkidle")
    page.locator(f'.map-node[data-node-id="{node}"]').click()
    panel = page.locator("[data-graph-files]")
    expect(panel.locator(f'[data-file-record="{record["id"]}"]')).to_be_visible()
    return page, panel, record


def test_thread_search_result_opens_the_existing_thread(graph_files):
    page, _url, _home, _source, _original, thread_id, _node = graph_files
    page, panel, _record = imported(graph_files)
    panel.locator('[name="query"]').fill("Library Project")
    result = submit_search(page, panel)
    assert any(row["entity_type"] == "thread" and row["thread_id"] == thread_id
               for row in result["hits"])
    panel.locator(f'a[href="/?thread={thread_id}"]').click()
    expect(page).to_have_url(f"{_url}/?thread={thread_id}")
    expect(page.locator('#notes textarea[name="text"]')).to_have_value("")


@pytest.mark.parametrize("language", ["de", "en"])
def test_graph_file_lifecycle_and_explicit_open(graph_files, language):
    page, url, _home, _source, original, _thread, node = graph_files
    choose_language(page, url, language)
    page.goto(url + "/map", wait_until="networkidle")
    page, panel, record = imported(graph_files)
    opens = []
    def intercept(route):
        arguments = route.request.post_data_json
        if arguments.get("action") != "open":
            route.continue_()
            return
        opens.append(arguments)
        route.fulfill(json={"ok": True, "result": {"status": "launch_requested",
                      "operation_id": arguments["operation_id"], "human_read_confirmed": False}})
    page.route("**/api/library/command", intercept)
    panel.locator(f'[data-file-record="{record["id"]}"]').click()
    expect(panel.locator("[data-file-preview]")).to_be_visible()
    expect(panel.locator("[data-file-body]")).to_contain_text("library-owl")
    assert not opens
    expect(panel.locator("[data-file-node]")).to_have_js_property("tagName", "SELECT")
    expect(panel.locator("[data-file-node] option", has_text="Library Project")).to_have_count(1)
    expect(panel.locator("[data-file-project] option", has_text="Library Project")).to_have_count(1)
    panel.locator("[data-file-name]").fill("renamed.txt")
    panel.locator('[data-file-action="rename"]').click()
    expect(panel.locator("[data-file-title]")).to_have_text("renamed.txt")
    panel.locator("[data-file-folder]").fill("Sorted/2026")
    panel.locator('[data-file-action="move"]').click()
    expect(panel.locator("[data-file-folder]")).to_have_value("Sorted/2026")
    page.wait_for_function("""async id => {
      const r=await fetch('/api/library/query?'+new URLSearchParams({action:'info',id}));
      return (await r.json()).result?.logical_path==='Sorted/2026/renamed.txt';
    }""", arg=record["id"])
    panel.locator('[data-file-action="open"]').click()
    expect(panel.locator("[data-file-message]")).to_contain_text(
        "Öffnen an das Standardprogramm" if language == "de" else "Opening requested")
    assert len(opens) == 1
    panel.locator('[data-file-action="trash"]').click()
    expect(panel.locator("[data-file-preview]")).not_to_be_visible()
    expect(panel.locator(f'[data-file-record="{record["id"]}"]')).to_have_count(0)
    panel.locator("[data-files-trash]").check()
    panel.locator(f'[data-file-record="{record["id"]}"]').click()
    expect(panel.locator('[data-file-action="restore"]')).to_be_visible()
    expect(panel.locator('[data-file-action="open"]')).not_to_be_visible()
    panel.locator('[data-file-action="restore"]').click()
    expect(panel.locator('[data-file-action="trash"]')).to_be_visible()
    panel.locator("[data-file-close]").click()
    panel.locator("[data-files-trash]").uncheck()
    panel.locator('[name="query"]').fill("library-owl")
    results = submit_search(page, panel)
    assert any(hit.get("record_id") == record["id"] for hit in results["hits"]), results
    expect(panel.locator(f'[data-file-record="{record["id"]}"]')).to_be_visible()
    panel.locator('[name="query"]').fill("renamed")
    results = submit_search(page, panel)
    assert any(hit.get("record_id") == record["id"] for hit in results["hits"]), results
    expect(panel.locator(f'[data-file-record="{record["id"]}"]')).to_be_visible()
    assert read(page, "info", id=record["id"])["revision"] == 5
    assert original.read_text() == "Unique content marker library-owl"
    # Visible filters carry IDs internally, while users choose project titles.
    panel.locator("[data-files-project]").select_option(node)
    panel.locator("[data-files-type]").select_option("document")
    panel.locator("[data-files-date-from]").fill("2000-01-01")
    panel.locator("[data-files-date-to]").fill("2099-12-31")
    results = submit_search(page, panel)
    assert any(hit.get("record_id") == record["id"] for hit in results["hits"]), results
    expect(panel.locator(f'[data-file-record="{record["id"]}"]')).to_be_visible()


def test_unknown_copy_result_reconciles_same_operation_without_replay(graph_files):
    page, panel, record = imported(graph_files)
    copies = []
    def lose_response(route):
        args = route.request.post_data_json
        if args.get("action") != "copy":
            route.continue_()
            return
        copies.append(args)
        response = route.fetch()
        assert response.json()["ok"]
        route.abort("failed")
    page.route("**/api/library/command", lose_response)
    panel.locator(f'[data-file-record="{record["id"]}"]').click()
    panel.locator("[data-file-name]").fill("copied.txt")
    panel.locator('[data-file-action="copy"]').click()
    expect(panel.locator('[data-file-action="copy"]')).to_be_disabled()
    expect(panel.locator("[data-file-name]")).to_be_disabled()
    expect(panel.locator("[data-file-check]")).to_be_visible()
    panel.locator("[data-file-check]").click()
    expect(panel.locator("[data-file-title]")).to_have_text("copied.txt")
    expect(panel.locator('[data-file-action="copy"]')).to_be_enabled()
    assert len(copies) == 1
    assert read(page, "list")["total"] == 2


def test_folder_root_is_explicit_and_no_handler_is_not_success(graph_files):
    page, panel, record = imported(graph_files)
    command(page, {"action": "move", "operation_id": "folder-layout", "id": record["id"],
                   "expected_revision": record["revision"], "data": {"folder": "Sorted"}})
    panel.locator("[data-files-folder]").fill("")
    panel.locator("[data-files-folder-open]").click()
    expect(panel.locator(f'[data-file-record="{record["id"]}"]')).to_have_count(0)
    panel.get_by_role("button", name="Ordner: Sorted", exact=True).click()
    expect(panel.locator(f'[data-file-record="{record["id"]}"]')).to_be_visible()
    expect(panel.get_by_role("button", name="Übergeordneter Ordner", exact=True)).to_be_visible()
    panel.locator(f'[data-file-record="{record["id"]}"]').click()
    def no_handler(route):
        route.fulfill(status=400, json={"ok": False, "code": "no_default_application", "error": "No default application"})
    page.route("**/api/library/command", no_handler)
    panel.locator('[data-file-action="open"]').click()
    expect(panel.locator("[data-file-message]")).to_contain_text("no_default_application")
    expect(panel.locator("[data-file-message]")).not_to_contain_text("Gespeichert")
    expect(panel.locator('[data-file-action="open"]')).to_be_enabled()


def test_late_preview_cannot_replace_new_selection_or_draft(graph_files):
    page, panel, first = imported(graph_files)
    second = command(page, {"action": "copy", "id": first["id"], "operation_id": "second-file",
                            "expected_revision": first["revision"], "data": {"filename": "second.txt"}})["record"]
    panel.locator("[data-files-all]").click()
    expect(panel.locator(f'[data-file-record="{second["id"]}"]')).to_be_visible()
    payload = {"ok": True, "result": read(page, "preview", id=first["id"])}
    held = []
    page.evaluate("""first => {
      const fetchOriginal=window.fetch;
      window.fetch=(input,...rest)=>fetchOriginal(input,...rest).then(response=>{
        const url=new URL(String(input),location.href);
        if(url.searchParams.get('action')==='preview' && url.searchParams.get('id')===first)
          response.clone().json().then(()=>requestAnimationFrame(()=>requestAnimationFrame(()=>{window.__oldPreviewDelivered=true;})));
        return response;
      });
    }""", first["id"])
    def hold_first(route):
        from urllib.parse import parse_qs, urlsplit
        query = parse_qs(urlsplit(route.request.url).query)
        if query.get("action") == ["preview"] and query.get("id") == [first["id"]]:
            held.append(route)
            return
        route.continue_()
    page.route("**/api/library/query?*", hold_first)
    panel.locator(f'[data-file-record="{first["id"]}"]').click()
    panel.locator(f'[data-file-record="{second["id"]}"]').click()
    expect(panel.locator("[data-file-title]")).to_have_text("second.txt")
    panel.locator("[data-file-name]").fill("unsaved-second-draft.txt")
    assert len(held) == 1
    held[0].fulfill(json=payload)
    page.wait_for_function("window.__oldPreviewDelivered === true")
    expect(panel.locator("[data-file-title]")).to_have_text("second.txt")
    expect(panel.locator("[data-file-name]")).to_have_value("unsaved-second-draft.txt")


def test_reconciled_failed_open_is_not_reported_saved(graph_files):
    page, panel, record = imported(graph_files)
    launches = []
    def unknown(route):
        args = route.request.post_data_json
        launches.append(args)
        route.fulfill(json={"ok": True, "result": {"status": "unknown"}})
    def failed_status(route):
        from urllib.parse import parse_qs, urlsplit
        if parse_qs(urlsplit(route.request.url).query).get("action") == ["operation"]:
            route.fulfill(json={"ok": True, "result": {"found": True,
                "result": {"status": "failed", "error": "external_open_failed"}}})
        else:
            route.continue_()
    page.route("**/api/library/command", unknown)
    page.route("**/api/library/query?*", failed_status)
    panel.locator(f'[data-file-record="{record["id"]}"]').click()
    panel.locator('[data-file-action="open"]').click()
    expect(panel.locator('[data-file-action="open"]')).to_be_disabled()
    panel.locator("[data-file-check]").click()
    expect(panel.locator("[data-file-message]")).to_contain_text("external_open_failed")
    expect(panel.locator("[data-file-message]")).not_to_contain_text("Gespeichert")
    expect(panel.locator('[data-file-action="open"]')).to_be_enabled()
    assert len(launches) == 1


def test_assignment_keeps_existing_links_and_uses_node_titles(graph_files):
    page, panel, record = imported(graph_files)
    _page, _url, _home, _source, _original, _thread, project = graph_files
    current = command(page, {"action": "assign", "operation_id": "initial-assignment", "id": record["id"],
                             "expected_revision": record["revision"], "data": {"node_ids": [project]}})["record"]
    panel.locator(f'[data-file-record="{record["id"]}"]').click()
    panel.locator("[data-file-node]").select_option(label="Supporting task · task")
    panel.locator('[data-file-action="assign"]').click()
    expect(panel.locator("[data-file-assignments]")).to_contain_text("Supporting task")
    expect(panel.locator("[data-file-assignments]")).to_contain_text("Library Project")
    changed = read(page, "info", id=record["id"])
    assert len(changed["node_ids"]) == 2 and project in changed["node_ids"]
    assert changed["revision"] == current["revision"] + 1
    panel.locator("[data-file-node]").select_option("")
    panel.locator('[data-file-action="assign"]').click()
    expect(panel.locator("[data-file-assignments]")).to_contain_text("Keine Knotenzuordnung")
    assert read(page, "info", id=record["id"])["node_ids"] == []


def test_script_and_unknown_format_remain_manageable_without_launch(graph_files):
    page, panel, record = imported(graph_files)
    requests = []
    page.on("request", lambda request: requests.append(request.post_data_json)
            if request.url.endswith("/api/library/command") and request.method == "POST" else None)
    panel.locator(f'[data-file-record="{record["id"]}"]').click()
    panel.locator("[data-file-name]").fill("source.py")
    panel.locator('[data-file-action="rename"]').click()
    expect(panel.locator("[data-file-title]")).to_have_text("source.py")
    expect(panel.locator('[data-file-action="open"]')).to_be_disabled()
    expect(panel.locator("[data-file-body]")).to_contain_text("library-owl")
    panel.locator("[data-file-name]").fill("unknown.mystery")
    panel.locator('[data-file-action="rename"]').click()
    expect(panel.locator("[data-file-title]")).to_have_text("unknown.mystery")
    expect(panel.locator("[data-file-body]")).to_contain_text("Keine sichere interne Vorschau")
    expect(panel.locator('[data-file-action="open"]')).to_be_disabled()
    expect(panel.locator('[data-file-action="trash"]')).to_be_enabled()
    assert all(request.get("action") != "open" for request in requests)
