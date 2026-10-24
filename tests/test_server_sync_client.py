"""Necessary replica data-loss, resume, dependency-boundary and integrity checks."""
import base64
import json
from pathlib import Path

import httpx
import pytest

from threaddesk.server_sync.client import ClientError, SyncClient, digest, scan_project
from threaddesk.server_sync.store import SyncStore


class Wire:
    def __init__(self, store, project):
        self.store, self.project = store, project
        self.transfers = []
        self.lose_ack = False
        self.fail_abort = False
        self.lose_abort_ack = False
        self.abort_calls = []
        self.lose_commit_ack = False
        self.lose_begin_ack = False
        self.abort_on_begin = False
        self.corrupt_download = False
        self.client = httpx.Client(base_url="https://sync.example", transport=httpx.MockTransport(self.handle))

    def handle(self, request):
        assert request.headers["authorization"] == "Bearer test-access-token"
        path = request.url.path.split("/")[4:]
        payload = json.loads(request.content) if request.content else {}
        if path == ["status"]:
            value = self.store.status(self.project)
        elif path == ["thread"]:
            value = {"context": {"files": []}}
        elif path == ["manifest"]:
            value = self.store.declare_manifest(self.project, **payload)
        elif path == ["files"]:
            value = {"files": self.store.list_files(self.project)}
        elif path[0] == "uploads":
            transfer = path[1]
            if request.method == "POST" and len(path) == 2:
                self.transfers.append(transfer)
                value = self.store.start_upload(self.project, transfer, **payload)
                if self.abort_on_begin:
                    value = self.store.abort_upload(self.project, transfer)
                if self.lose_begin_ack and value['state'] == 'receiving':
                    self.lose_begin_ack = False
                    raise httpx.ReadError("Injected lost begin acknowledgement", request=request)
            elif request.method == "GET":
                value = self.store.upload_status(self.project, transfer)
            elif path[-1] == "abort":
                self.abort_calls.append(transfer)
                if self.fail_abort:
                    return httpx.Response(503, json={"error": "injected_abort_failure"})
                value = self.store.abort_upload(self.project, transfer)
                if self.lose_abort_ack:
                    self.lose_abort_ack = False
                    raise httpx.ReadError("Injected lost abort acknowledgement", request=request)
            elif request.method == "PATCH":
                value = self.store.append_chunk(self.project, transfer, payload["offset"], base64.b64decode(payload["data_base64"]))
                if self.lose_ack:
                    self.lose_ack = False
                    raise httpx.ReadError("Injected lost acknowledgement", request=request)
            else:
                value = self.store.finish_upload(self.project, transfer)
                if self.lose_commit_ack:
                    self.lose_commit_ack = False
                    raise httpx.ReadError("Injected lost commit acknowledgement", request=request)
        elif path[0] == "revisions":
            data = self.store.read_revision(self.project, path[1])
            return httpx.Response(200, content=b"corrupt" if self.corrupt_download else data)
        else:
            raise AssertionError(path)
        return httpx.Response(200, json=value)


def fixture(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    store = SyncStore(tmp_path / "server")
    project = store.create_project("Example")["id"]
    store.set_offline(project, True)
    wire = Wire(store, project)
    client = SyncClient("https://sync.example", "test-access-token", project, root,
                        state_dir=tmp_path / "checkpoint", transport=wire.client)
    return root, store, project, wire, client


def publish(store, project, data, base=None, path="note.md", transfer="server1"):
    store.start_upload(project, transfer, path, len(data), digest(data), base)
    if data:
        store.append_chunk(project, transfer, 0, data)
    return store.finish_upload(project, transfer)


def test_scan_new_files_and_external_symlink_secret_dependencies(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (tmp_path / "outside.txt").write_text("private")
    (root / "readme.md").write_text("[missing](missing.txt) [outside](../outside.txt)")
    (root / ".env").write_text("PASSWORD=private")
    (root / "link.txt").symlink_to(tmp_path / "outside.txt")
    files, issues = scan_project(root)
    assert [f["path"] for f in files] == ["readme.md"]
    assert len(issues) >= 3
    (root / "late.txt").write_text("added")
    assert "late.txt" in {f["path"] for f in scan_project(root)[0]}
    assert "private" not in json.dumps(files)


def test_bidirectional_updates_keep_original_versions_and_conflicts(tmp_path):
    root, store, project, wire, client = fixture(tmp_path)
    (root / "note.md").write_bytes(b"one")
    assert client.sync_once()["state"] == "ready"
    original = store.list_files(project)[0]["heads"][0]
    second = publish(store, project, b"two", original["revision"])
    assert client.sync_once()["state"] == "ready"
    assert (root / "note.md").read_bytes() == b"two"
    assert any(p.read_bytes() == b"one" for p in (root / ".threaddesk-sync-conflicts/previous").iterdir())
    previous_map = [json.loads(p.read_text()) for p in (root / ".threaddesk-sync-conflicts/previous").glob("*.json")]
    assert previous_map[0]["path"] == "note.md" and previous_map[0]["sha256"] == digest(b"one")
    # Both sides edit from the same common base; server must retain both heads.
    (root / "note.md").write_bytes(b"local three")
    publish(store, project, b"remote three", second["revision"], transfer="server2")
    status = client.sync_once()
    assert status["conflict_count"] == 1
    heads = store.list_files(project)[0]["heads"]
    assert {store.read_revision(project, h["revision"]) for h in heads} == {b"local three", b"remote three"}
    assert (root / "note.md").read_bytes() == b"local three"
    assert any(p.read_bytes() == b"remote three" for p in (root / ".threaddesk-sync-conflicts/remote").iterdir())
    remote_map = [json.loads(p.read_text()) for p in (root / ".threaddesk-sync-conflicts/remote").glob("*.json")]
    assert remote_map[0]["path"] == "note.md" and remote_map[0]["kind"] == "remote"
    client.sync_once()
    assert len(store.list_files(project)[0]["heads"]) == 2
    client.close()


def test_lost_ack_restart_reuses_transfer_and_server_offset(tmp_path):
    root, store, project, wire, client = fixture(tmp_path)
    data = b"a" * (256 * 1024 + 23)
    (root / "large.bin").write_bytes(data)
    wire.lose_ack = True
    with pytest.raises(httpx.ReadError):
        client.sync_once()
    client.close()
    restarted = SyncClient("https://sync.example", "test-access-token", project, root,
                           state_dir=tmp_path / "checkpoint", transport=wire.client)
    assert restarted.sync_once()["state"] == "ready"
    assert len(set(wire.transfers)) == 1
    heads = store.list_files(project)[0]["heads"]
    assert len(heads) == 1
    assert store.read_revision(project, heads[0]["revision"]) == data
    restarted.close()


def test_remote_integrity_failure_cannot_replace_local_bytes(tmp_path):
    root, store, project, wire, client = fixture(tmp_path)
    (root / "note.md").write_bytes(b"original")
    client.sync_once()
    original = store.list_files(project)[0]["heads"][0]
    publish(store, project, b"server change", original["revision"])
    wire.corrupt_download = True
    status = client.sync_once()
    assert status["local_issues"]
    assert status["state"] != "ready"
    assert (root / "note.md").read_bytes() == b"original"
    client.close()


def test_publication_race_retains_both_local_inodes(tmp_path, monkeypatch):
    root, store, project, wire, client = fixture(tmp_path)
    target = root / "note.md"
    target.write_bytes(b"old")
    import os
    original_rename = os.rename

    def racing_rename(source, destination, **kwargs):
        original_rename(source, destination, **kwargs)
        target.write_bytes(b"concurrent writer")

    monkeypatch.setattr(os, "rename", racing_rename)
    with pytest.raises(ClientError, match="Concurrent file"):
        client._install("note.md", b"remote", digest(b"old"))
    assert target.read_bytes() == b"concurrent writer"
    assert any(p.read_bytes() == b"old" for p in (root / ".threaddesk-sync-conflicts/previous").iterdir())
    client.close()


def test_checkpoint_identity_and_cleartext_protection(tmp_path):
    root, store, project, wire, client = fixture(tmp_path)
    client.close()
    with pytest.raises(ClientError, match="different server"):
        SyncClient("https://sync.example", "another-account", project, root,
                   state_dir=tmp_path / "checkpoint", transport=wire.client)
    with pytest.raises(ClientError, match="HTTPS"):
        SyncClient("http://sync.example", "token", project, root)
    with pytest.raises(ClientError, match="outside"):
        SyncClient("https://sync.example", "token", project, root, state_dir=root / "checkpoint")


def test_fifo_refused_and_parent_symlink_swap_cannot_read_external_bytes(tmp_path, monkeypatch):
    import os
    from threaddesk.server_sync import client as module
    root = tmp_path / "tree"
    root.mkdir()
    os.mkfifo(root / "pipe")
    files, issues = scan_project(root)
    assert files == [] and issues
    inside = root / "inside"
    inside.mkdir()
    (inside / "file.txt").write_bytes(b"inside")
    external = tmp_path / "outside"
    external.mkdir()
    (external / "file.txt").write_bytes(b"sensitive external")
    original_read = module._read_at

    def swap_parent(descriptor, name):
        inside.rename(root / "retained")
        inside.symlink_to(external, target_is_directory=True)
        return original_read(descriptor, name)

    monkeypatch.setattr(module, "_read_at", swap_parent)
    assert module._read(root, "inside/file.txt") == b"inside"


def test_documented_cli_flags_and_invalid_interval(tmp_path, monkeypatch, capsys):
    from threaddesk.server_sync import client as module
    captured = {}

    class Stub:
        def __init__(self, url, token, project, root, **kwargs):
            captured.update(url=url, token=token, project=project, root=root, **kwargs)
        def sync_once(self):
            return {"state": "metadata_only"}
        def close(self):
            pass

    monkeypatch.setattr(module, "SyncClient", Stub)
    token_file = tmp_path / "token"
    token_file.write_text("token-value\n")
    args = ["--url", "http://127.0.0.1:8765", "--project", "project1", "--root", str(tmp_path),
            "--token-file", str(token_file), "--allow-http-loopback"]
    assert module.main(args) == 0
    assert captured["project"] == "project1" and captured["allow_insecure_loopback"]
    assert json.loads(capsys.readouterr().out)["state"] == "metadata_only"
    with pytest.raises(SystemExit):
        module.main(args + ["--interval", "nan"])


def test_recovery_mapping_failure_keeps_original_and_downloaded_bytes(tmp_path, monkeypatch):
    root, store, project, wire, client = fixture(tmp_path)
    target = root / "note.md"
    target.write_bytes(b"local original")

    def fail_mapping(*args, **kwargs):
        raise OSError("Injected metadata write failure")

    monkeypatch.setattr(client, "_recovery_metadata", fail_mapping)
    with pytest.raises(OSError, match="metadata write"):
        client._install("note.md", b"remote changed", digest(b"local original"))
    assert target.read_bytes() == b"local original"
    receipt = publish(store, project, b"remote conflict")
    head = {"revision": receipt["revision"], "sha256": digest(b"remote conflict"), "size": len(b"remote conflict")}
    with pytest.raises(OSError, match="metadata write"):
        client._conflict_copy("note.md", head)
    assert any(p.read_bytes() == b"remote conflict" for p in (root / ".threaddesk-sync-conflicts/remote").glob("*.copy"))
    assert target.read_bytes() == b"local original"
    client.close()


def test_changed_pending_transfer_cancellation_frees_reservation_only_after_ack(tmp_path):
    root, store, project, wire, client = fixture(tmp_path)
    (root / "large.bin").write_bytes(b"a" * (256 * 1024 + 23))
    wire.lose_ack = True
    with pytest.raises(httpx.ReadError):
        client.sync_once()
    old_transfer = wire.transfers[0]
    (root / "large.bin").write_bytes(b"updated local content")
    wire.fail_abort = True
    with pytest.raises(httpx.HTTPStatusError):
        client.sync_once()
    assert wire.transfers == [old_transfer]
    assert client.db.execute("SELECT transfer FROM uploads").fetchone()[0] == old_transfer
    assert store.upload_status(project, old_transfer)["state"] == "receiving"
    wire.fail_abort = False
    assert client.sync_once()["state"] == "ready"
    assert store.upload_status(project, old_transfer)["state"] == "aborted"
    assert len(set(wire.transfers)) == 2
    assert store.status(project)["active_transfers"] == 0
    head = store.list_files(project)[0]["heads"][0]
    assert store.read_revision(project, head["revision"]) == b"updated local content"
    assert (root / "large.bin").read_bytes() == b"updated local content"
    # A late cancellation of an already committed transfer preserves its receipt
    # and uses that actual revision as the base for the next local edit.
    wire.lose_commit_ack = True
    (root / "large.bin").write_bytes(b"committed but reply lost")
    with pytest.raises(httpx.ReadError):
        client.sync_once()
    (root / "large.bin").write_bytes(b"next edit after lost reply")
    assert client.sync_once()["state"] == "ready"
    assert len(store.list_files(project)[0]["heads"]) == 1
    retained = {store.read_revision(project, item["revision"]) for item in store.history(project, "large.bin")}
    assert retained == {b"updated local content", b"committed but reply lost", b"next edit after lost reply"}
    client.close()


def test_vcs_internals_are_excluded_but_explicit_dependencies_still_block(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").mkdir()
    (root / ".git/config").write_text("private repository configuration")
    (root / ".hg").write_text("worktree pointer")
    (root / "file.txt").write_text("project content")
    files, issues = scan_project(root)
    assert [f["path"] for f in files] == ["file.txt"] and issues == []
    _, issues = scan_project(root, references=[".git/config"])
    assert issues
    (root / ".svn").symlink_to(tmp_path, target_is_directory=True)
    assert scan_project(root)[1]


def test_server_canceled_unchanged_upload_restarts_with_durable_new_id(tmp_path):
    root, store, project, wire, client = fixture(tmp_path)
    path = root / 'large.bin'
    path.write_bytes(b'previous committed original')
    assert client.sync_once()['state'] == 'ready'
    original = store.list_files(project)[0]['heads'][0]
    data = b'updated bytes' * (256 * 1024 // len(b'updated bytes') + 100)
    path.write_bytes(data)
    wire.lose_ack = True
    with pytest.raises(httpx.ReadError):
        client.sync_once()
    canceled_id = wire.transfers[-1]
    assert store.upload_status(project, canceled_id)['state'] == 'receiving'
    assert store.abort_upload(project, canceled_id)['state'] == 'aborted'
    client.close()
    restarted = SyncClient('https://sync.example', 'test-access-token', project, root,
                           state_dir=tmp_path/'checkpoint', transport=wire.client)
    # A lost acknowledgement for the replacement begin must retain the NEW
    # checkpoint, so a second process restart does not allocate a third ID.
    wire.lose_begin_ack = True
    with pytest.raises(httpx.ReadError):
        restarted.sync_once()
    replacement_id = restarted.db.execute('SELECT transfer FROM uploads').fetchone()[0]
    assert replacement_id != canceled_id
    assert store.upload_status(project, replacement_id)['state'] == 'receiving'
    restarted.close()
    final = SyncClient('https://sync.example', 'test-access-token', project, root,
                       state_dir=tmp_path/'checkpoint', transport=wire.client)
    try:
        assert final.sync_once()['state'] == 'ready'
        assert wire.transfers[-1] == replacement_id
        assert store.upload_status(project, canceled_id)['state'] == 'aborted'
        assert store.read_revision(project, original['revision']) == b'previous committed original'
        heads = store.list_files(project)[0]['heads']
        assert len(heads) == 1 and store.read_revision(project, heads[0]['revision']) == data
        assert len(store.history(project, 'large.bin')) == 2
        assert path.read_bytes() == data
    finally:
        final.close()


def test_server_repeated_cancellation_is_bounded_and_later_recoverable(tmp_path):
    root, store, project, wire, client = fixture(tmp_path)
    (root/'note.md').write_bytes(b'unchanged local original')
    wire.abort_on_begin = True
    status = client.sync_once()
    assert status['state'] != 'ready'
    assert any('repeatedly canceled' in issue for issue in status['local_issues'])
    assert len(wire.transfers) == 2
    assert client.db.execute('SELECT transfer FROM uploads').fetchone()[0] == wire.transfers[-1]
    assert all(store.upload_status(project, value)['state'] == 'aborted' for value in wire.transfers)
    wire.abort_on_begin = False
    assert client.sync_once()['state'] == 'ready'
    assert (root/'note.md').read_bytes() == b'unchanged local original'
    client.close()


@pytest.mark.parametrize('edited_after_resolution',[False,True],ids=['adopt-browser-choice','preserve-new-local-edit'])
def test_browser_resolution_of_other_head_adopts_only_unchanged_acknowledged_local_bytes(tmp_path,edited_after_resolution):
    from fastapi.testclient import TestClient
    from threaddesk.server_sync.app import create_app
    from threaddesk.server_sync.auth import provision

    root=tmp_path/'project';root.mkdir();local=root/'note.txt';local.write_bytes(b'original')
    token=provision(tmp_path/'server','alice')
    headers={'Authorization':'Bearer '+token}
    app=create_app(tmp_path/'server',public_origin='https://testserver')
    with TestClient(app,base_url='https://testserver') as http:
        pid=http.post('/api/projects',headers=headers,json={'title':'Project'}).json()['id']
        api='/api/projects/'+pid
        assert http.put(api+'/offline',headers=headers,json={'enabled':True}).status_code==200
        client=SyncClient('https://testserver',token,pid,root,state_dir=tmp_path/'checkpoint',transport=http)
        assert client.sync_once()['state']=='ready'
        initial=http.get(api+'/files',headers=headers).json()['files'][0]['heads'][0]
        local.write_bytes(b'local concurrent')
        remote=b'browser concurrent'
        uri=api+'/uploads/browser-edit'
        assert http.post(uri,headers=headers,json={'path':'note.txt','size':len(remote),
                        'sha256':digest(remote),'base_revision':initial['revision']}).status_code==200
        assert http.patch(uri,headers=headers,json={'offset':0,'data_base64':base64.b64encode(remote).decode()}).status_code==200
        remote_revision=http.post(uri+'/commit',headers=headers).json()['revision']
        assert client.sync_once()['state']=='conflict'
        assert client._base('note.txt')['sha256']==digest(b'local concurrent')
        assert client.db.execute('SELECT COUNT(*) FROM uploads').fetchone()[0]==0
        heads=http.get(api+'/files',headers=headers).json()['files'][0]['heads']
        # This is the same protected endpoint used by the browser's explicit choice.
        response=http.post(api+'/resolve',headers=headers,json={'path':'note.txt',
                           'expected_heads':[head['revision'] for head in heads], 'chosen_revision':remote_revision})
        assert response.status_code==200,response.text
        client.close()
        if edited_after_resolution:
            local.write_bytes(b'genuinely newer local edit')
        restarted=SyncClient('https://testserver',token,pid,root,state_dir=tmp_path/'checkpoint',transport=http)
        try:
            status=restarted.sync_once()
            assert http.get(api+'/revisions/'+initial['revision'],headers=headers).content==b'original'
            history=http.get(api+'/history',headers=headers,params={'path':'note.txt'}).json()['versions']
            contents={http.get(api+'/revisions/'+version['revision'],headers=headers).content for version in history}
            assert {b'original',b'local concurrent',remote}<=contents
            if edited_after_resolution:
                assert status['state']=='conflict'
                assert local.read_bytes()==b'genuinely newer local edit'
                current_heads=http.get(api+'/files',headers=headers).json()['files'][0]['heads']
                assert len(current_heads)==2 and len(history)==4
                assert {http.get(api+'/revisions/'+head['revision'],headers=headers).content for head in current_heads}=={
                    remote,b'genuinely newer local edit'}
            else:
                assert status['state']=='ready',status
                assert local.read_bytes()==remote and len(history)==3
                assert any(copy.read_bytes()==b'local concurrent' for copy in (root/'.threaddesk-sync-conflicts/previous').glob('*.copy'))
                assert restarted._base('note.txt')['revision']==remote_revision
        finally:
            restarted.close()


@pytest.mark.parametrize('removed',[False,True],ids=['reverted-to-current-head','removed-unpublished-file'])
def test_unpublished_transfer_is_closed_before_reverted_or_removed_checkpoint_is_forgotten(tmp_path,removed):
    root,store,project,wire,client=fixture(tmp_path)
    path=root/'large.bin'
    path.write_bytes(b'original')
    assert client.sync_once()['state']=='ready'
    original=store.list_files(project)[0]['heads'][0]
    path.write_bytes(b'changed'*(256*1024//7+100))
    wire.lose_ack=True
    with pytest.raises(httpx.ReadError):
        client.sync_once()
    transfer=wire.transfers[-1]
    assert store.status(project)['active_transfers']==1
    if removed:
        path.unlink()
    else:
        path.write_bytes(b'original')
    assert client.sync_once()['state']=='ready'
    assert store.upload_status(project,transfer)['state']=='aborted'
    assert store.status(project)['active_transfers']==0
    assert client.db.execute('SELECT COUNT(*) FROM uploads').fetchone()[0]==0
    assert path.read_bytes()==b'original'
    assert store.read_revision(project,original['revision'])==b'original'
    assert len(store.history(project,'large.bin'))==1
    client.close()


def test_uncertain_abort_of_reverted_transfer_keeps_checkpoint_until_terminal_proof(tmp_path):
    root,store,project,wire,client=fixture(tmp_path)
    path=root/'large.bin';path.write_bytes(b'original')
    client.sync_once()
    path.write_bytes(b'changed'*(256*1024//7+100));wire.lose_ack=True
    with pytest.raises(httpx.ReadError):
        client.sync_once()
    transfer=wire.transfers[-1];path.write_bytes(b'original')
    wire.fail_abort=True
    with pytest.raises(httpx.HTTPStatusError):
        client.sync_once()
    assert client.db.execute('SELECT transfer FROM uploads').fetchone()[0]==transfer
    assert store.status(project)['active_transfers']==1
    assert path.read_bytes()==b'original'
    wire.fail_abort=False;wire.lose_abort_ack=True
    with pytest.raises(httpx.ReadError):
        client.sync_once()
    assert client.db.execute('SELECT transfer FROM uploads').fetchone()[0]==transfer
    assert store.upload_status(project,transfer)['state']=='aborted'
    client.close()
    restarted=SyncClient('https://sync.example','test-access-token',project,root,
                         state_dir=tmp_path/'checkpoint',transport=wire.client)
    try:
        assert restarted.sync_once()['state']=='ready'
        assert restarted.db.execute('SELECT COUNT(*) FROM uploads').fetchone()[0]==0
        assert store.status(project)['active_transfers']==0
        assert path.read_bytes()==b'original'
    finally:
        restarted.close()


def test_committed_pending_receipt_is_acknowledged_without_aborting_published_version(tmp_path):
    root,store,project,wire,client=fixture(tmp_path)
    path=root/'note.md';path.write_bytes(b'original');client.sync_once()
    path.write_bytes(b'published new version');wire.lose_commit_ack=True
    with pytest.raises(httpx.ReadError):
        client.sync_once()
    transfer=wire.transfers[-1]
    assert store.upload_status(project,transfer)['state']=='committed'
    before=list(wire.abort_calls)
    assert client.sync_once()['state']=='ready'
    assert wire.abort_calls==before
    assert client.db.execute('SELECT COUNT(*) FROM uploads').fetchone()[0]==0
    assert store.upload_status(project,transfer)['state']=='committed'
    assert path.read_bytes()==b'published new version'
    assert len(store.history(project,'note.md'))==2
    client.close()
