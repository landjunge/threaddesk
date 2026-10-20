"""Faults in disposable state must not turn failed canonical writes into success."""
import sqlite3

import pytest

from threaddesk.core.models import new_thread
from threaddesk.core.search import SearchError
from threaddesk.services.search import LocalFileOwnerPolicy, SearchService
from threaddesk.storage.sqlite_store import SQLiteStore


def test_sqlite_engine_rollback_during_index_update_is_reported(tmp_path):
    store = SQLiteStore(tmp_path)
    thread = new_thread("Original title")
    store.save_thread(thread)
    search = SearchService(store, LocalFileOwnerPolicy(store.workspace_path))
    search.set_enabled(True)
    for _ in range(5):
        if search.rebuild_batch()["status"] == "ready":
            break
    # Real SQLite RAISE(ROLLBACK), analogous to an engine-aborted transaction;
    # no actual disk is filled and no product database is involved.
    store.connection.execute("""CREATE TRIGGER synthetic_index_abort BEFORE INSERT
        ON thread_search_meta BEGIN SELECT RAISE(ROLLBACK,'synthetic engine rollback'); END""")
    store.connection.commit()
    thread.title = "Uncommitted replacement"
    with pytest.raises(sqlite3.Error):
        store.save_thread(thread)
    assert store.get_thread(thread.id).title == "Original title"
    assert search.search("Original").hits
    search.close()
    store.connection.close()


def test_failed_publication_state_write_degrades_instead_of_missing_new_content(tmp_path):
    store = SQLiteStore(tmp_path)
    thread = new_thread("Original title")
    store.save_thread(thread)
    search = SearchService(store, LocalFileOwnerPolicy(store.workspace_path))
    search.set_enabled(True)
    for _ in range(5):
        if search.rebuild_batch()["status"] == "ready":
            break
    store.connection.execute("""CREATE TRIGGER synthetic_state_abort BEFORE INSERT
        ON app_state WHEN NEW.key='local_search'
        BEGIN SELECT RAISE(ABORT,'synthetic state failure'); END""")
    store.connection.commit()
    thread.title = "Replacement orchid"
    store.save_thread(thread)
    assert store.get_thread(thread.id).title == "Replacement orchid"
    assert search.search("orchid").mode == "bounded_scan"
    assert search.search("orchid").hits
    search.close()
    store.connection.close()


def test_failed_source_reads_still_consume_the_byte_budget(tmp_path, monkeypatch):
    from threaddesk.core.search import CALL_BYTES, RECORD_BYTES, SearchError
    from threaddesk.storage.json_store import JsonStore
    store = JsonStore(tmp_path)
    search = SearchService(store, LocalFileOwnerPolicy(store.workspace_path))
    search.set_enabled(True)
    attempts = []
    def failed_read(exact_id):
        attempts.append(exact_id)
        raise SearchError("source_invalid")
    monkeypatch.setattr(search.adapter, "read", failed_read)
    monkeypatch.setattr(search.adapter, "candidates", lambda *a, **k: ((str(i), None) for i in range(500)))
    page = search.search("needle")
    assert len(attempts) <= CALL_BYTES // RECORD_BYTES
    assert "byte_budget" in page.reasons and page.next_cursor
    search.close()


def test_time_budget_keeps_a_real_continuation(tmp_path, monkeypatch):
    from threaddesk.services import search as search_module
    store = SQLiteStore(tmp_path)
    for _ in range(2):
        store.save_thread(new_thread("needle"))
    search = SearchService(store, LocalFileOwnerPolicy(store.workspace_path))
    search.set_enabled(True)
    ticks = [1000.0]
    monkeypatch.setattr(search_module, "monotonic", lambda: ticks[0])
    original = search.adapter.read
    def elapsed_read(exact_id):
        value = original(exact_id)
        ticks[0] += .2
        return value
    monkeypatch.setattr(search.adapter, "read", elapsed_read)
    page = search.search("needle")
    assert len(page.hits) == 1 and page.scanned == 1
    assert page.next_cursor and "time_budget" in page.reasons
    followup = search.search("needle", cursor=page.next_cursor)
    assert len(followup.hits) == 1 and followup.hits[0].thread_id != page.hits[0].thread_id
    search.close()
    store.connection.close()


@pytest.mark.parametrize("backend", ["json", "sqlite"])
def test_optional_state_damage_does_not_block_backup(tmp_path, backend):
    from threaddesk.storage.json_store import JsonStore
    from threaddesk.storage.portable_backup import download_backup, restore_backup
    store = JsonStore(tmp_path / "source") if backend == "json" else SQLiteStore(tmp_path / "source")
    thread = new_thread("Backup preserved")
    store.save_thread(thread)
    search = SearchService(store, LocalFileOwnerPolicy(store.workspace_path))
    search.set_enabled(True)
    if backend == "json":
        (store.workspace_path / "local-search.json").write_text("broken")
    else:
        store.connection.execute("DROP TABLE search_index")
        store.connection.commit()
    archive = download_backup(store)
    restored = restore_backup(archive, tmp_path / "profiles")
    reopened = JsonStore(restored) if backend == "json" else SQLiteStore(restored)
    assert reopened.get_thread(thread.id).title == "Backup preserved"
    search.close()
    if backend == "sqlite":
        reopened.connection.close()
        store.connection.close()


@pytest.mark.parametrize("indexed", [True, False])
def test_sqlite_interruption_pauses_without_losing_keyset_position(tmp_path, monkeypatch, indexed):
    store = SQLiteStore(tmp_path)
    thread = new_thread("needle")
    store.save_thread(thread)
    search = SearchService(store, LocalFileOwnerPolicy(store.workspace_path))
    search.set_enabled(True)
    if indexed:
        for _ in range(5):
            if search.rebuild_batch()["status"] == "ready":
                break
    connection = search.adapter._reader()
    class OnceInterrupted:
        interrupted = False
        def execute(self, sql, params=()):
            if "ORDER BY" in sql and not self.interrupted:
                self.interrupted = True
                raise sqlite3.OperationalError("interrupted")
            return connection.execute(sql, params)
        def set_progress_handler(self, *args):
            return connection.set_progress_handler(*args)
    proxy = OnceInterrupted()
    monkeypatch.setattr(search.adapter, "_reader", lambda: proxy)
    page = search.search("needle")
    assert not page.hits and page.next_cursor and "time_budget" in page.reasons
    resumed = search.search("needle", cursor=page.next_cursor)
    assert [hit.thread_id for hit in resumed.hits] == [thread.id]
    search.close()
    store.connection.close()


# Independent reviewer counterexample, unchanged below.
def ready(search):
 search.set_enabled(True)
 for _ in range(20):
  state=search.rebuild_batch()
  if state['status']=='ready':return
 pytest.fail('synthetic rebuild did not finish')

def test_optional_marker_delete_denial_must_not_leave_ready_stale_index(tmp_path):
 store=SQLiteStore(tmp_path/'workspace');thread=new_thread('Original lavender');store.save_thread(thread)
 search=SearchService(store,LocalFileOwnerPolicy(store.workspace_path));ready(search)
 denials=[]
 def authorizer(action,table,*rest):
  if action==sqlite3.SQLITE_DELETE and table=='search_index':
   denials.append(table);return sqlite3.SQLITE_DENY
  return sqlite3.SQLITE_OK
 store.connection.set_authorizer(authorizer)
 try:
  thread.title='Updated orchid';store.save_thread(thread)
  assert store.get_thread(thread.id).title=='Updated orchid'
  state=search.status();page=search.search('orchid')
  print('E08_OPTIONAL_MARKER_DENIED',{'denials':len(denials),'status':state['status'],'mode':page.mode,'hits':len(page.hits),'complete':page.complete,'reasons':page.reasons})
  assert denials
  assert page.hits,'successful canonical save must remain searchable through fallback after optional index error'
 finally:
  store.connection.set_authorizer(None);search.close();store.connection.close()


# Strong independent in-flight regression: trigger precedes the page.
@pytest.mark.parametrize('indexed',[True,False])
def test_committed_save_with_preexisting_state_fault_invalidates_page(tmp_path,indexed):
 store=SQLiteStore(tmp_path/'workspace');thread=new_thread('Original orchid');store.save_thread(thread)
 search=SearchService(store,LocalFileOwnerPolicy(store.workspace_path));search.set_enabled(True)
 if indexed:
  for _ in range(20):
   if search.rebuild_batch()['status']=='ready':break
 # Install the fault before the page starts. Only the real save commits during policy evaluation.
 store.connection.execute("CREATE TRIGGER synthetic_state_abort BEFORE INSERT ON app_state WHEN NEW.key='local_search' BEGIN SELECT RAISE(ABORT,'synthetic optional state failure'); END")
 store.connection.commit()
 class SaveInPolicy(LocalFileOwnerPolicy):
  saved=False
  def can_read_current(self,doc):
   if not self.saved:
    self.saved=True
    current=store.get_thread(doc.thread_id);current.title='Replacement tulip';store.save_thread(current)
   return True
 search.policy=SaveInPolicy(store.workspace_path)
 try:
  with pytest.raises(SearchError,match='generation_changed'):
   search.search('orchid',limit=1)
  assert store.get_thread(thread.id).title=='Replacement tulip'
 finally:search.close();store.connection.close()
