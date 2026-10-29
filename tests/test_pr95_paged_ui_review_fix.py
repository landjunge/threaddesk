"""Real browser command pages preserve data, offsets and mutation identity."""
import json
import os
import socket
import threading
import time
from contextlib import contextmanager

import pytest
import uvicorn
from playwright.sync_api import expect, sync_playwright

from threaddesk.api.service import ThreadService
from threaddesk.core.models import KnowledgeNode
from threaddesk.services.graph_views import GraphViewService
from threaddesk.services.trash import TrashService
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore
from threaddesk.ui.server import create_app


@pytest.fixture(params=[JsonStore, SQLiteStore], ids=["json", "sqlite"])
def desk(tmp_path, monkeypatch, request):
    root = tmp_path / "workspace"
    store = request.param(root)
    monkeypatch.setenv("THREADDESK_HOME", str(root))
    monkeypatch.setenv("THREADDESK_STORAGE", "sqlite" if request.param is SQLiteStore else "json")
    monkeypatch.setenv("THREADDESK_SOURCE_ROOTS", "[]")

    @contextmanager
    def open_page(path="/trash?lang=en"):
        if isinstance(store, SQLiteStore):
            store.connection.close()
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        url = f"http://127.0.0.1:{listener.getsockname()[1]}"
        server = uvicorn.Server(uvicorn.Config(create_app(), log_level="error"))
        worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        worker.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started and time.monotonic() < deadline:
                time.sleep(.05)
            assert server.started
            with sync_playwright() as play:
                browser = play.chromium.launch(executable_path=os.environ.get("THREADDESK_CHROMIUM") or None)
                try:
                    page = browser.new_page(viewport={"width": 1440, "height": 1000})
                    errors, calls = [], []
                    page.on("pageerror", lambda error: errors.append(str(error)))

                    def observed(response):
                        if response.url == url + "/api/commands":
                            calls.append({"request": response.request.post_data_json,
                                          "response": response.json(), "status": response.status})

                    page.on("response", observed)
                    page.goto(url + path, wait_until="networkidle")
                    yield page, url, calls
                    assert not errors, errors
                finally:
                    browser.close()
        finally:
            server.should_exit = True
            worker.join(timeout=10)
            listener.close()
            assert not worker.is_alive()

    yield store, open_page
    if isinstance(store, SQLiteStore):
        store.connection.close()


def command(page, identity, arguments=None, *, operation=None, revision=None):
    return page.evaluate("""async request => {
      const catalog = await (await fetch('/api/commands/catalog?limit=1')).json();
      const envelope = {version:1, workspace_id:catalog.workspace_id,
                        command:request.identity, arguments:request.arguments};
      if (request.operation !== null) envelope.operation_id = request.operation;
      if (request.revision !== null) envelope.expected_revision = request.revision;
      try { return {ok:true, result:await window.threadDeskCommand(envelope)}; }
      catch (error) { return {ok:false, code:error.code || error.message}; }
    }""", {"identity": identity, "arguments": arguments or {}, "operation": operation, "revision": revision})


def test_large_trash_list_renders_next_page_and_restores_original_identity(desk):
    store, open_page = desk
    service, trash, identities = ThreadService(store), TrashService(store), []
    for number in range(51):
        thread = service.create(f"Retained {number:03} Ä🧭漢")
        identities.append(thread.id)
        trash.move(kind="thread", object_id=thread.id, expected_revision=thread.revision,
                   operation_id=f"fixture-trash-{number}")

    with open_page() as (page, _url, calls):
        expect(page.locator("[data-trash-items] > li")).to_have_count(50)
        expect(page.locator("[data-trash-next]")).to_be_visible()
        pages = [row for row in calls if row["request"]["command"] == "trash.list"]
        assert len(pages) > 1 and all("result_page" in row["response"] for row in pages)
        assert len({row["response"]["result_digest"] for row in pages}) == 1
        for previous, current in zip(pages, pages[1:]):
            assert current["request"]["result_offset"] == previous["response"]["next_offset"]
            assert current["request"]["result_digest"] == previous["response"]["result_digest"]
        page.locator("[data-trash-next]").click()
        expect(page.locator("[data-trash-items] > li")).to_have_count(51)
        expect(page.locator("[data-trash-next]")).to_be_hidden()
        row = page.locator("[data-trash-items] > li").filter(has_text="Retained 000")
        row.get_by_role("button", name="Restore", exact=True).click()
        expect(row).to_have_count(0)
        expect(page.locator("[data-trash-message]")).to_contain_text("Restored")
        restored = command(page, "get_thread", {"id": identities[0]})
        assert restored["ok"] and restored["result"]["id"] == identities[0]
        assert command(page, "trash.list", {"limit": 50})["result"]["total"] == 50


def test_paged_unicode_mutation_reuses_exact_operation_and_replay_creates_no_second_thread(desk):
    _store, open_page = desk
    description = "Ä🧭漢" * 3000
    arguments = {"action": "create", "data": {"title": "Single paged mutation", "description": description}}
    with open_page() as (page, _url, calls):
        first = command(page, "thread_manage", arguments, operation="unicode-create", revision=0)
        repeated = command(page, "thread_manage", arguments, operation="unicode-create", revision=0)
        assert first["ok"] and repeated["ok"]
        assert first["result"]["thread"]["id"] == repeated["result"]["thread"]["id"]
        assert first["result"]["thread"]["description"] == (
            '<untrusted source="threaddesk.description">\n' + description + '\n</untrusted>')
        assert repeated["result"]["thread"]["revision"] == 1
        threads = command(page, "list_threads", {"include_archived": True})
        assert len(threads["result"]) == 1
        pages = [row for row in calls if row["request"]["command"] == "thread_manage"]
        assert len(pages) >= 4 and all("result_page" in row["response"] for row in pages)
        for row in pages:
            assert row["request"]["operation_id"] == "unicode-create"
            assert row["request"]["arguments"] == arguments
            assert row["request"]["expected_revision"] == 0
        assert any(len(row["response"]["result_page"].encode("utf-16-le")) // 2 !=
                   len(row["response"]["result_page"]) for row in pages)


@pytest.mark.parametrize("fault,code", [("offset", "invalid_result_page"), ("next", "invalid_result_page"),
                                       ("digest", "result_changed"), ("content", "result_changed")])
def test_reader_rejects_inconsistent_pages_without_returning_partial_result(desk, fault, code):
    store, open_page = desk
    thread = ThreadService(store).create("Unchanged fixture", "Ä🧭漢" * 3000)
    with open_page() as (page, _url, _calls):
        intercepted = []

        def corrupt(route):
            request = route.request.post_data_json
            response = route.fetch()
            if request["command"] == "get_thread" and request.get("result_offset"):
                data = response.json()
                intercepted.append(request)
                if fault == "offset":
                    data["offset"] += 1
                elif fault == "next":
                    data["next_offset"] = data["offset"]
                elif fault == "digest":
                    data["result_digest"] = "0" * 64
                else:
                    data["result_page"] = data["result_page"].replace("Ä", "Ö", 1)
                route.fulfill(response=response, json=data)
            else:
                route.fulfill(response=response)

        page.route("**/api/commands", corrupt)
        result = command(page, "get_thread", {"id": thread.id})
        assert result == {"ok": False, "code": code} and intercepted
        page.unroute("**/api/commands", corrupt)
        restored = command(page, "get_thread", {"id": thread.id})
        assert restored["ok"] and restored["result"]["description"] == (
            '<untrusted source="threaddesk.description">\n' + "Ä🧭漢" * 3000 + '\n</untrusted>')


def test_read_snapshot_is_pinned_across_real_graph_result_pages(desk):
    store, open_page = desk
    for number in range(55):
        store.save_node(KnowledgeNode(f"node-{number}", "task", f"{number} " + "🧭漢" * 100))
    with open_page() as (page, _url, calls):
        result = command(page, "graph.query", {"limit": 100})
        assert result["ok"] and len(result["result"]["nodes"]) == 55
        pages = [row for row in calls if row["request"]["command"] == "graph.query"]
        assert len(pages) > 1
        stamp = pages[0]["response"]["snapshot_at"]
        assert all(row["request"]["snapshot_at"] == stamp for row in pages[1:])
        assert all(row["response"]["snapshot_at"] == stamp for row in pages)


def test_large_saved_views_keep_existing_thin_save_get_list_and_browser_load_contract(desk):
    store, open_page = desk
    project = ThreadService(store).create_node("project", "Visible large view")
    views = GraphViewService(store)
    for number in range(100):
        views.manage({"action": "save", "id": f"listed-{number}", "operation_id": f"fixture-view-{number}",
                      "expected_revision": 0, "data": {"title": f"{number:03} " + "Ä🧭漢" * 50}})
    positions = {}
    for number in range(100):
        identity = f"node-{number:03}-" + "x" * 91
        store.save_node(KnowledgeNode(identity, "task", f"Saved node {number}"))
        positions[identity] = {"x": number + .1234567890123456, "y": number + .9876543210987654, "fixed": False}
    positions[project.id] = {"x": 500, "y": 300, "fixed": True}
    state = {"camera": {"x": 500, "y": 300, "scale": 1}, "positions": positions,
             "selection": list(positions)[:99] + [project.id], "filters": {"mode": "work"}}
    request = {"action": "save", "id": "large-thin-view", "operation_id": "large-thin-save",
               "expected_revision": 0, "data": {"title": "Large thin view", "state": state}}
    assert len(json.dumps(request).encode()) > 24000
    with open_page("/map?lang=en") as (page, url, _calls):
        result = page.evaluate("""async body => {
          const response = await window.threadDeskWrite('/api/graph/views', {
            headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
          return {status:response.status,body:await response.json()};
        }""", request)
        assert result["status"] == 200 and result["body"]["result"]["view"]["revision"] == 1
        saved = page.request.get(url + "/api/graph/views/large-thin-view")
        assert saved.ok and len(saved.body()) > 24000 and saved.json()["state"]["positions"] == positions
        listing = page.request.get(url + "/api/graph/views?limit=100")
        assert listing.ok and len(listing.body()) > 24000 and listing.json()["next_offset"] == 100
        page.reload(wait_until="networkidle")
        page.locator(".graph-view-tools > summary").click()
        expect(page.locator("[data-map-view] option")).to_have_count(102)
        page.locator("[data-map-view]").select_option("large-thin-view")
        page.locator("[data-map-view-load]").click()
        expect(page.locator(f'[data-node-id="{project.id}"]')).to_have_attribute("data-fixed", "true")
        expect(page.locator("[data-map-view-message]")).to_be_hidden()
