"""Only synthetic tmp_path workspaces; no product profiles or network."""
from dataclasses import asdict
import json
from pathlib import Path

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.core.models import new_thread
from threaddesk.core.search import CANDIDATES, RECORD_BYTES, SearchError
from threaddesk.services.search import LocalFileOwnerPolicy, SearchService
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore


@pytest.fixture(autouse=True)
def functional_budget_clock(monkeypatch):
    # Correctness tests must not depend on an idle host. Real wall/CPU time is
    # measured by the benchmark; the time-stop contract has its own probe.
    from threaddesk.services import search
    monkeypatch.setattr(search, "monotonic", lambda: 1000.0)


@pytest.fixture(params=[JsonStore, SQLiteStore], ids=["json", "sqlite"])
def store(request, tmp_path):
    instance = request.param(tmp_path / "synthetic")
    yield instance
    if hasattr(instance, "connection"):
        instance.connection.close()


def service(store, policy=None):
    return SearchService(store, policy or LocalFileOwnerPolicy(store.workspace_path))


def build(search):
    search.set_enabled(True)
    for _ in range(50):
        state = search.rebuild_batch()
        if state["status"] not in {"cleaning", "building"}:
            return state
    pytest.fail("bounded build did not finish")


def put(store, title="Title token", description="Description lavender", notes="Notes marigold"):
    thread = new_thread(title, description)
    thread.context.notes = notes
    store.save_thread(thread)
    return thread


def all_hits(search, query, **kwargs):
    hits, cursor = [], None
    for _ in range(200):
        page = search.search(query, cursor=cursor, **kwargs)
        assert page.scanned <= CANDIDATES and page.source_bytes <= 8 * RECORD_BYTES
        hits.extend(page.hits)
        cursor = page.next_cursor
        if cursor is None:
            return hits
    pytest.fail("scan did not finish")


def test_default_disabled_and_default_authority_denied(store):
    put(store)
    with pytest.raises(SearchError, match="authority_unavailable"):
        SearchService(store).search("token")
    assert service(store).search("token").mode == "disabled"
    assert service(store).status()["enabled"] is False


def test_initial_current_fields_original_revision_and_plaintext(store, monkeypatch):
    thread = put(store, notes="<script> marigold plain text")
    thread.context.agent_state["hidden"] = "secretword"
    store.save_thread(thread)
    search = service(store)
    state = build(search)
    monkeypatch.setattr(store, "get_thread", lambda *a: pytest.fail("legacy get_thread used"))
    monkeypatch.setattr(store, "list_threads", lambda *a, **k: pytest.fail("whole-list read used"))
    for query, name in [("token", "title"), ("lavender", "description"), ("marigold", "notes")]:
        hit = search.search(query).hits[0]
        assert hit.field == name and hit.thread_id == thread.id
        assert hit.thread_revision == thread.revision
        assert search.resolve(hit)[hit.start:hit.end].lower() == query
        assert len(hit.snippet) <= 240
    assert not search.search("secretword").hits
    if isinstance(store, SQLiteStore):
        assert state["status"] == "ready" and search.search("marigold").mode == "fts5"
        assert store.connection.execute("SELECT count(*) FROM search_index WHERE entity_type LIKE 'thread:%'").fetchone()[0] == 3
    else:
        page = search.search("marigold")
        assert not page.complete and "json_external_writers_unverified" in page.reasons


def test_save_rename_archive_restore_and_delete_are_current(store):
    api = ThreadService(store)
    thread = api.create("Original token")
    api.set_note("historic lavender", thread.id)
    snap = api.snapshot("synthetic", thread.id)
    search = service(store)
    build(search)
    old = search.search("lavender").hits[0]
    api.rename(thread.id, "Renamed orchid")
    api.set_description("Current peony", thread.id)
    api.set_note("current marigold", thread.id)
    assert not search.search("lavender").hits
    assert search.search("orchid").hits and search.search("peony").hits
    with pytest.raises(SearchError, match="revision_changed"):
        search.resolve(old)
    api.archive(thread.id)
    assert not search.search("marigold").hits
    assert search.search("marigold", include_archived=True).hits
    api.unarchive(thread.id)
    api.restore(snap.id)
    assert search.search("lavender").hits and not search.search("marigold").hits
    store.delete_thread(thread.id)
    assert not search.search("lavender").hits


def test_project_filter_is_not_authority_and_policy_is_fresh(store):
    first, second = put(store), put(store)
    first.context.extra["organization"] = {"project_id": "project-a"}
    store.save_thread(first)
    class Policy(LocalFileOwnerPolicy):
        epoch = "one"
        denied = set()
        def generation(self):
            return super().generation() + self.epoch
        def can_read_current(self, doc):
            return doc.thread_id not in self.denied
    policy = Policy(store.workspace_path)
    search = service(store, policy)
    build(search)
    assert [hit.thread_id for hit in search.search("token", project_id="project-a").hits] == [first.id]
    page = search.search("token", limit=1)
    policy.denied = {first.id, second.id}
    policy.epoch = "two"
    with pytest.raises(SearchError, match="generation_changed"):
        search.search("token", limit=1, cursor=page.next_cursor)
    assert not search.search("token").hits
    with pytest.raises(SearchError, match="authority_unavailable"):
        SearchService(store).search("token", project_id="project-a")


def test_mid_page_policy_change_discards_all_hits(store):
    put(store)
    class Policy(LocalFileOwnerPolicy):
        def can_read_current(self, doc):
            self._generation = "revoked"
            return True
    search = service(store, Policy(store.workspace_path))
    build(search)
    with pytest.raises(SearchError, match="generation_changed"):
        search.search("token")


@pytest.mark.parametrize("change", ["query", "limit", "project", "restart", "write", "disable", "rebuild"])
def test_cursor_binding(store, change):
    first = put(store)
    put(store)
    search = service(store)
    build(search)
    page = search.search("token", limit=1)
    assert page.next_cursor
    args = {"limit": 1, "cursor": page.next_cursor}
    query = "token"
    if change == "query": query = "lavender"
    elif change == "limit": args["limit"] = 2
    elif change == "project": args["project_id"] = "project-a"
    elif change == "restart": search = service(store)
    elif change == "write":
        first.title = "Changed token"
        store.save_thread(first)
    elif change == "disable": search.set_enabled(False)
    elif change == "rebuild": search.rebuild_batch()
    with pytest.raises(SearchError, match="generation_changed|cursor_expired"):
        search.search(query, **args)
    search.close()


def test_transaction_rollback_preserves_content_and_search_generation(store):
    thread = put(store)
    search = service(store)
    build(search)
    generation = search.status()["generation"]
    with pytest.raises(RuntimeError):
        with store.transaction():
            thread.title = "Rollbackmarker"
            store.save_thread(thread)
            raise RuntimeError("synthetic rollback")
    assert search.status()["generation"] == generation
    assert not search.search("Rollbackmarker").hits
    assert search.search("token").hits


@pytest.mark.parametrize("query,limit", [("", 20), ("x"*513, 20), ("x\x00", 20), ("x", True), ("x", 101), (" ".join(["x"]*17), 20)])
def test_query_bounds(store, query, limit):
    search = service(store)
    with pytest.raises(SearchError, match="invalid_search_query"):
        search.search(query, limit=limit)


def test_literal_operators_do_not_expand_query(store):
    put(store, title="alpha only", description="", notes="")
    search = service(store)
    build(search)
    assert not search.search("alpha OR absent").hits
    assert not search.search('title:alpha').hits
    assert not search.search('" OR 1=1 --').hits


def test_more_than_1000_and_candidate_budget(store):
    with store.transaction():
        for _ in range(1050):
            put(store, title="needle", description="", notes="")
    search = service(store)
    build(search)
    hits = all_hits(search, "needle", limit=100)
    assert len(hits) == 1050
    assert len({hit.thread_id for hit in hits}) == 1050
    # Dense/no-match fallback must stop after a bounded amount of source work.
    if isinstance(store, JsonStore):
        page = search.search("absent")
        assert page.scanned <= 500 and not page.complete and page.next_cursor
    search.close()


def test_oversize_source_is_not_materialized_or_falsely_complete(store):
    put(store, notes="largeword " + "x"*RECORD_BYTES)
    search = service(store)
    state = build(search)
    page = search.search("largeword")
    assert not page.hits and not page.complete
    assert "source_unreadable_or_over_limit" in page.reasons


def test_missing_fts_and_failed_index_update_do_not_break_canonical_save(tmp_path):
    store = SQLiteStore(tmp_path)
    thread = put(store)
    search = service(store)
    build(search)
    store.connection.execute("DROP TABLE search_index")
    store.connection.commit()
    assert search.search("token").mode == "bounded_scan"
    thread.context.notes = "replacement peony"
    store.save_thread(thread)
    assert store.get_thread(thread.id).context.notes == "replacement peony"
    assert search.status()["status"] == "stale"
    assert search.search("peony").hits
    for _ in range(20):
        state = search.rebuild_batch()
        if state["status"] == "ready": break
    assert state["status"] == "ready"
    assert search.search("peony").mode == "fts5"
    store.delete_thread(thread.id)
    store.connection.close()


def test_json_legacy_query_is_read_only_and_inplace_changes_current(tmp_path, monkeypatch):
    store = JsonStore(tmp_path)
    thread = new_thread("Legacy token")
    path = store.threads_dir / (thread.id + ".json")
    path.write_text(json.dumps(thread.to_dict()))
    search = service(store)
    build(search)
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in tmp_path.rglob("*") if p.is_file()}
    assert search.search("token").hits[0].thread_revision == 0
    after = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in tmp_path.rglob("*") if p.is_file()}
    assert before == after and not (tmp_path / "thread-revisions").exists()
    data = thread.to_dict()
    data["title"] = "Changed iris"
    path.write_text(json.dumps(data))
    assert not search.search("token").hits
    assert search.search("iris").hits
    assert not search.search("iris").complete


def test_corrupt_optional_state_does_not_break_normal_store(store):
    search = service(store)
    build(search)
    if isinstance(store, JsonStore):
        (store.root / "local-search.json").write_text("broken")
    else:
        store.connection.execute("UPDATE app_state SET value='broken' WHERE key='local_search'")
        store.connection.commit()
    put(store)
    assert search.search("token").mode == "unavailable"
    assert store.list_threads()


def test_cli_local_enable_rebuild_search_and_disable(store, monkeypatch, capsys):
    from threaddesk.ui import cli
    put(store)
    monkeypatch.setattr(cli, "_svc", lambda: ThreadService(store))
    assert cli.main(["--lang", "en", "search", "--enable", "--rebuild", "--batches", "20", "lavender"]) == 0
    value = json.loads(capsys.readouterr().out)
    assert value["hits"][0]["field"] == "description"
    assert cli.main(["search", "--disable"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "disabled"


def test_second_instance_write_invalidates_cursor_and_updates_index(store):
    thread = put(store)
    put(store)
    search = service(store)
    build(search)
    page = search.search("token", limit=1)
    other = type(store)(store.workspace_path)
    changed = other.get_thread(thread.id)
    changed.description = "newinstance iris"
    other.save_thread(changed)
    with pytest.raises(SearchError, match="generation_changed"):
        search.search("token", limit=1, cursor=page.next_cursor)
    assert search.search("iris").hits
    if hasattr(other, "connection"):
        other.connection.close()
    search.close()


def test_reopen_recreated_empty_fts_cannot_report_ready(tmp_path):
    store = SQLiteStore(tmp_path)
    put(store)
    search = service(store)
    build(search)
    store.connection.execute("DROP TABLE search_index")
    store.connection.commit()
    store.connection.close()
    reopened = SQLiteStore(tmp_path)
    search = service(reopened)
    assert search.status()["status"] == "degraded"
    assert search.search("token").mode == "bounded_scan"
    assert search.search("token").hits
    build(search)
    assert search.search("token").mode == "fts5"
    reopened.connection.close()


def test_rebuild_with_intervening_write_remains_partial(tmp_path):
    store = SQLiteStore(tmp_path)
    put(store)
    search = service(store)
    search.set_enabled(True)
    assert search.rebuild_batch()["status"] == "building"
    put(store)
    assert search.rebuild_batch()["status"] == "building"
    assert search.rebuild_batch()["status"] == "partial"
    assert search.search("token").mode == "bounded_scan"
    build(search)
    assert search.status()["status"] == "ready"
    store.connection.close()


def test_no_fts_module_uses_labeled_fallback(tmp_path, monkeypatch):
    from threaddesk.storage import search_sqlite
    store = SQLiteStore(tmp_path)
    put(store)
    store.connection.execute("DROP TABLE search_index")
    store.connection.commit()
    monkeypatch.setattr(search_sqlite, "FTS_SQL", "CREATE VIRTUAL TABLE search_index USING td_missing_fts5(x)")
    search = service(store)
    assert search.set_enabled(True)["status"] == "no_fts5"
    assert search.search("token").mode == "bounded_scan"
    assert search.search("token").hits
    thread = put(store)
    store.delete_thread(thread.id)
    assert store.list_threads()
    store.connection.close()


def test_json_stale_revision_navigation_detects_inplace_edit(tmp_path):
    store = JsonStore(tmp_path)
    thread = new_thread("legacy token")
    path = store.threads_dir / (thread.id + ".json")
    path.write_text(json.dumps(thread.to_dict()))
    search = service(store)
    build(search)
    hit = search.search("token").hits[0]
    thread.title = "changed title"
    path.write_text(json.dumps(thread.to_dict()))
    with pytest.raises(SearchError, match="revision_changed"):
        search.resolve(hit)


def test_expired_cursor_is_closed_and_rejected(store):
    put(store)
    put(store)
    search = service(store)
    build(search)
    page = search.search("token", limit=1)
    search._cursors[page.next_cursor]["created"] -= 301
    with pytest.raises(SearchError, match="cursor_expired"):
        search.search("token", limit=1, cursor=page.next_cursor)


def test_json_external_links_and_corrupt_source_are_not_hits(tmp_path):
    store = JsonStore(tmp_path / "workspace")
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps(new_thread("outside secretmarker").to_dict()))
    try:
        (store.threads_dir / "outside.json").symlink_to(outside)
    except OSError:
        pytest.skip("host cannot create synthetic symlink")
    (store.threads_dir / "broken.json").write_text("corrupt")
    search = service(store)
    build(search)
    page = search.search("secretmarker")
    assert not page.hits and not page.complete
    assert "source_unreadable_or_over_limit" in page.reasons
