"""Synthetic browser views follow the server; real replica requirements do not."""
import hashlib
import json
import sqlite3

from threaddesk.server_sync.store import SyncStore


def entry(data):
    return {'path':'note.txt','size':len(data),'sha256':hashlib.sha256(data).hexdigest()}


def publish(store,pid,transfer,data,base=None):
    value=entry(data)
    store.start_upload(pid,transfer,value['path'],value['size'],value['sha256'],base)
    store.append_chunk(pid,transfer,0,data)
    return store.finish_upload(pid,transfer)['revision']


def test_browser_snapshot_does_not_block_later_desktop_writes_or_mutate_idle_journal(tmp_path):
    store=SyncStore(tmp_path);pid=store.create_project('Project')['id'];store.set_offline(pid,True)
    first=publish(store,pid,'browser',b'browser')
    assert store.declare_manifest(pid,[entry(b'browser')],[],'browser-server')['state']=='ready'
    # Reproduce an existing persisted browser snapshot, then a later desktop edit.
    second=publish(store,pid,'desktop',b'desktop',first)
    store.declare_manifest(pid,[entry(b'desktop')],[],'desktop')
    with sqlite3.connect(store.db_path) as db:
        before=db.execute('SELECT files,updated_at FROM manifests WHERE device=?',('browser-server',)).fetchone()
    assert json.loads(before[0])==[entry(b'browser')]
    assert store.status(pid)['state']=='ready'
    assert store.status(pid)['state']=='ready'
    with sqlite3.connect(store.db_path) as db:
        assert db.execute('SELECT files,updated_at FROM manifests WHERE device=?',('browser-server',)).fetchone()==before
    # An in-flight stale browser POST cannot reintroduce obsolete requirements.
    assert store.declare_manifest(pid,[entry(b'browser')],[],'browser-server')['state']=='ready'
    assert store.read_revision(pid,first)==b'browser'
    assert store.read_revision(pid,second)==b'desktop'


def test_live_browser_view_preserves_real_replica_disagreement_conflicts_and_integrity(tmp_path):
    store=SyncStore(tmp_path);pid=store.create_project('Project')['id'];store.set_offline(pid,True)
    first=publish(store,pid,'browser',b'browser')
    store.declare_manifest(pid,[],[],'browser-server')
    store.declare_manifest(pid,[entry(b'browser')],[],'offline-device')
    second=publish(store,pid,'desktop',b'desktop',first)
    assert store.declare_manifest(pid,[entry(b'desktop')],[],'desktop')['state']=='blocked'
    assert 'Device manifests disagree: note.txt' in store.status(pid)['issues']
    assert store.declare_manifest(pid,[entry(b'desktop')],[],'offline-device')['state']=='ready'
    third=publish(store,pid,'concurrent',b'conflict',first)
    assert store.status(pid)['state']=='conflict'
    store.resolve(pid,'note.txt',[second,third],second)
    assert store.status(pid)['state']=='ready'
    with sqlite3.connect(store.db_path) as db:
        db.execute('UPDATE versions SET body=? WHERE revision=?',(b'broken',second))
    assert store.status(pid)['state']=='blocked'
