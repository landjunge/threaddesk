"""Fresh-workspace CLI/loopback acceptance, runnable by the visible bridge.

Every action uses the existing Client and a fresh command process. The report
contains request/response hashes and checked conclusions, never tokens/history.
This script does not establish the principal of the process that launches it.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import ProxyHandler, Request, build_opener
from xml.etree import ElementTree
from zipfile import ZipFile

from check_workspace_commands import Client


def digest(value):
    body = value if isinstance(value, bytes) else json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(body).hexdigest()


def public_notes_equal(thread, text):
    return thread["notes"] == '<untrusted source="threaddesk.notes">\n' + text + '\n</untrusted>'


def catalogue(client):
    rows, offset = [], 0
    while offset is not None:
        page = client.call("command.catalog", {"limit": 10, "offset": offset})
        rows.extend(page["commands"])
        offset = page["next_offset"]
    return {row["id"]: row for row in rows}


def actor_checks(client):
    human = client.call("actors.human", {"name": "Acceptance owner", "color_token": "moss"}, operation="actor-human")
    agent = client.call("actors.agent", {"name": "Acceptance agent", "person_id": human["id"],
                                       "agent_type": "chatgpt", "provider": "fixture-only"}, operation="actor-agent")
    client.call("actors.rename", {"actor_id": human["id"], "name": "Retained owner"}, operation="actor-rename")
    client.call("actors.recolor", {"actor_id": human["id"], "color_token": "sea"}, operation="actor-recolor")
    listed = client.call("actors.list")["items"]
    assert {human["id"], agent["id"]} <= {row["id"] for row in listed}
    person = client.call("actors.appearance", {"actor_id": human["id"]})
    assistant = client.call("actors.appearance", {"actor_id": agent["id"]})
    assert person["name"] == "Retained owner" and person["color_token"] == assistant["color_token"] == "sea"
    assert assistant["person_id"] == human["id"] and assistant["ai"] is True
    return {"human_id": human["id"], "agent_id": agent["id"], "shared_color_readback": True}


def module_checks(client, thread, project):
    commands = [{"id": name, "capability": capability} for name, capability in (
        ("nodes", "read_nodes"), ("thread", "read_thread"), ("board", "read_whiteboard"),
        ("append", "append_whiteboard"), ("records", "read_own_data"))]
    commands.append({"id": "record", "capability": "write_own_record", "action": "acceptance:write",
                     "required_approvals": ["acceptance:write"]})
    manifest = {"id": "acceptance", "name": "Declarative acceptance", "version": "1", "manifest_version": 1,
                "read_scopes": ["knowledge:project", "thread:read", "whiteboard:read"],
                "write_actions": ["whiteboard:append", "acceptance:write"], "approvals": ["acceptance:write"],
                "commands": commands}
    installed = client.call("modules.install", {"manifest": manifest}, operation="module-install")
    assert installed["enabled"] is False
    client.call("module.acceptance.thread", {"id": thread}, error="disabled")
    assert any(row["manifest"]["id"] == "acceptance" for row in client.call("modules.list")["items"])
    enable = {"id": "acceptance", "enabled": True, "approvals": ["acceptance:write"]}
    client.call("modules.enable", enable, operation="module-enable")
    assert project in {row["id"] for row in client.call("module.acceptance.nodes", {"kind": "project"})["items"]}
    state = client.call("module.acceptance.thread", {"id": thread})
    appended = client.call("module.acceptance.append", {"id": thread, "actor": "Declarative acceptance",
        "actor_type": "system", "entry_type": "note", "content": "Module append readback"},
        operation="module-append", revision=state["revision"])
    assert appended["entry"]["id"] in {row["id"] for row in client.call("module.acceptance.board", {"id": thread})["items"]}
    own = {"record_id": "sample", "value": {"fixture": True}}
    client.call("module.acceptance.record", own, operation="module-record", revision=0)
    records = client.call("module.acceptance.records")
    assert records["revision"] == 1 and records["records"]["sample"] == own["value"]
    before = client.catalog()["revision"]
    changed = deepcopy(manifest)
    changed["version"] = "2"
    changed["commands"][1]["input_schema"] = {"properties": {"id": {"maxLength": 1}}}
    client.call("modules.update", {"manifest": changed}, operation="module-schema")
    assert client.catalog()["revision"] != before
    client.call("module.acceptance.thread", {"id": thread}, error="disabled")
    client.call("modules.enable", enable, operation="module-reenable-schema")
    client.call("module.acceptance.thread", {"id": thread}, error="validation_error")
    restricted = {**deepcopy(manifest), "version": "3", "read_scopes": ["knowledge:project", "whiteboard:read"]}
    client.call("modules.update", {"manifest": restricted}, operation="module-revoke")
    client.call("modules.enable", enable, operation="module-reenable-rights")
    client.call("module.acceptance.thread", {"id": thread}, error="permission_required")
    assert client.call("module.acceptance.records")["records"]["sample"] == own["value"]
    client.call("modules.enable", {"id": "acceptance", "enabled": False}, operation="module-disable")
    client.call("module.acceptance.records", error="disabled")
    client.call("modules.uninstall", {"id": "acceptance"}, operation="module-uninstall")
    client.call("module.acceptance.records", error="command_not_found")
    assert not any(row["manifest"]["id"] == "acceptance" for row in client.call("modules.list")["items"])
    return {"six_capabilities": True, "live_schema_and_rights": True, "uninstalled": True}


def gate_and_search(client, thread, specs):
    fields = specs["gate.set"]["input_schema"]["properties"]
    policy = {key: index + 30 for index, (key, value) in enumerate(fields.items()) if value.get("type") == "integer"}
    assert set(policy) == {"max_execute_day", "max_execute_thread_day", "max_handoff_day", "max_handoff_thread_day", "cooldown_seconds"}
    policy["cooldown_seconds"] = 0
    client.call("gate.set", policy, operation="gate-policy")
    assert all(client.call("gate.status")["policy"][key] == value for key, value in policy.items())
    client.call("gate.freeze", {"frozen": True}, operation="gate-freeze")
    assert client.call("gate.status")["frozen"]
    client.call("gate.freeze", {"frozen": False}, operation="gate-unfreeze")
    assert client.call("gate.status")["frozen"] is False
    client.call("search.configure", {"enabled": True}, operation="owner-search-enable")
    client.call("search.rebuild", {"batches": 100}, operation="owner-search-build")
    found = client.call("search.query", {"query": "OwnerLocalNeedle", "pages": 20})
    assert any(hit["thread_id"] == thread for page in found["pages"] for hit in page["hits"])
    assert client.call("search.status")["enabled"]
    client.call("search.configure", {"enabled": False}, operation="owner-search-disable")
    assert client.call("search.status")["enabled"] is False
    return {"real_policy_fields": sorted(policy), "owner_cli_content_search": True, "search_disabled_after_check": True}


def resume_import(client, root, thread):
    folder = root / "import-originals"
    folder.mkdir()
    contents = [b"Current accessible original", b"Original supplied after the partial import"]
    paths = [folder / "available.txt", folder / "supplied-later.txt"]
    paths[0].write_bytes(contents[0])
    manifest = {"files": [{"path": str(path), "original_path": path.name, "source_ref": "acceptance-" + str(index),
                           "thread_id": thread, "sha256": digest(contents[index]), "size": len(contents[index])}
                          for index, path in enumerate(paths)], "expected_count": 2}
    initial = client.call("library_manage", {"action": "import", "data": {"manifest": manifest}}, operation="partial-import")
    assert initial["complete"] is False and any(row["status"] == "missing" for row in initial["files"])
    paths[1].write_bytes(contents[1])
    resumed = client.call("library.resume", {"import_operation_id": "partial-import"}, operation="resume-partial-import")
    assert resumed["complete"]
    readback = client.call("library_query", {"action": "import_status", "operation_id": "partial-import"})
    assert readback["complete"] and len(readback["files"]) == 2
    assert [digest(path.read_bytes()) for path in paths] == [digest(body) for body in contents]
    return {"original_import_operation": "partial-import", "resume_command_operation": "resume-partial-import",
            "record_ids": [row["record_id"] for row in readback["files"]], "original_sha256": [digest(body) for body in contents]}


def exports(client, project):
    results = []
    for format_name in ("json", "markdown", "csv", "xlsx", "svg", "pdf", "zip"):
        result = client.call("export.write", {"node_ids": [project], "format": format_name, "language": "en"}, operation="export-" + format_name)
        path = Path(result["path"])
        assert path.is_relative_to(client.workspace)
        body = path.read_bytes()
        assert digest(body) == result["sha256"] and len(body) == result["size"] and result["executed"] is False
        if format_name == "json":
            assert project in json.dumps(json.loads(body))
        elif format_name == "markdown":
            assert "Operations project" in body.decode()
        elif format_name == "csv":
            assert any(row["id"] == project for row in csv.DictReader(io.StringIO(body.decode("utf-8-sig"))))
        elif format_name in {"xlsx", "zip"}:
            with ZipFile(io.BytesIO(body)) as archive:
                assert archive.testzip() is None
        elif format_name == "svg":
            assert ElementTree.fromstring(body).tag.endswith("svg")
        else:
            assert body.startswith(b"%PDF-")
        results.append({"format": format_name, **result})
    return results


def backup_and_profiles(client, thread):
    original_workspace = client.workspace_id
    backup = client.call("backup.create", operation="backup-create")
    body = Path(backup["path"]).read_bytes()
    assert digest(body) == backup["sha256"]
    verified = client.call("backup.verify", {"path": backup["path"]})
    assert verified["verified"] and verified["sha256"] == backup["sha256"]
    restored = client.call("backup.restore", {"path": backup["path"], "sha256": backup["sha256"],
                           "confirmation": "restore_as_new_profile"}, operation="backup-restore")
    profile = Path(restored["profile_path"])
    assert profile.parent == client.workspace / "profiles"
    client.workspace_id = client.catalog()["workspace_id"]
    assert client.workspace_id != original_workspace
    assert public_notes_equal(client.call("get_thread", {"id": thread}), "OwnerLocalNeedle preserved notes")
    assert client.call("profiles.list")["active"] == profile.name
    client.call("profiles.original", operation="profile-original")
    client.workspace_id = client.catalog()["workspace_id"]
    assert client.workspace_id == original_workspace
    client.call("profiles.activate", {"name": profile.name}, operation="profile-activate")
    client.workspace_id = client.catalog()["workspace_id"]
    assert client.call("profiles.list")["active"] == profile.name
    client.call("profiles.original", operation="profile-original-again")
    client.workspace_id = client.catalog()["workspace_id"]
    assert client.workspace_id == original_workspace
    assert public_notes_equal(client.call("get_thread", {"id": thread}), "OwnerLocalNeedle preserved notes")
    return {"sha256": backup["sha256"], "restored_profile": profile.name, "original_workspace_preserved": True}


def http_get(url, token=None):
    headers = {"Authorization": "Bearer " + token} if token else {}
    with build_opener(ProxyHandler({})).open(Request(url, headers=headers), timeout=15) as response:
        return response.read(), response.headers


@contextmanager
def loopback_server(root, env, *, sync_data=None):
    """Use original apps/real sockets; no source or backend monkeypatches."""
    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    url = "http://127.0.0.1:" + str(listener.getsockname()[1])
    child_env = {**env, "TD_ACCEPT_FD": str(listener.fileno()), "TD_ACCEPT_URL": url}
    if sync_data:
        child_env["TD_ACCEPT_SYNC_DATA"] = str(sync_data)
    program = (
        "import os,socket,uvicorn; from pathlib import Path; "
        "from threaddesk.ui.server import create_app as ui; "
        "from threaddesk.server_sync.app import create_app as sync; "
        "data=os.environ.get('TD_ACCEPT_SYNC_DATA'); "
        "app=sync(Path(data),public_origin=os.environ['TD_ACCEPT_URL'],allow_http_loopback=True) if data else ui(); "
        "listener=socket.socket(fileno=int(os.environ['TD_ACCEPT_FD'])); "
        "uvicorn.Server(uvicorn.Config(app,log_level='error',access_log=False,proxy_headers=False,"
        "lifespan='on' if data else 'off')).run(sockets=[listener])"
    )
    log_path = root / "loopback-server.log"
    with log_path.open("wb") as log:
        log_path.chmod(0o600)
        process = subprocess.Popen([sys.executable, "-c", program], env=child_env, stdout=log, stderr=log,
                                   pass_fds=(listener.fileno(),))
    listener.close()
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            assert process.poll() is None, "Owned loopback server exited before readiness"
            try:
                http_get(url + ("/" if sync_data else "/api/commands/catalog?limit=1"))
                break
            except OSError:
                time.sleep(.1)
        else:
            raise AssertionError("Owned loopback server readiness timed out")
        yield url
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def network_checks(client, root, thread, artifacts, clients):
    peer_root = root / "peer"
    peer_root.mkdir(mode=0o700)
    peer = Client(peer_root, client.binary)
    clients.append(peer)
    with loopback_server(root, client.env) as own_url, loopback_server(peer_root, peer.env) as peer_url:
        for artifact in artifacts:
            body, headers = http_get(own_url + artifact["download_path"])
            assert digest(body) == artifact["sha256"] and len(body) == artifact["size"]
            assert headers.get("X-Content-Type-Options") == "nosniff"
        room = client.call("room.create", {"name": "Loopback acceptance"}, operation="room-create")
        client.call("room.select", {"room_id": room["id"]}, operation="room-select")
        code = client.call("room.invite", {"role": "member"}, operation="room-invite")
        peer.call("room.join", {"code": code, "peer_base": own_url, "own_base": peer_url}, operation="room-join")
        assert peer.call("room.status")["current"]["id"] == room["id"]
        current = client.call("get_thread", {"id": thread})
        entry = client.call("whiteboard.append", {"id": thread, "actor": "Acceptance owner", "actor_type": "human",
            "entry_type": "note", "content": "Explicitly shared loopback entry", "room_id": room["id"]},
            operation="room-entry", revision=current["revision"])["entry"]
        assert peer.call("room.sync", operation="room-sync-peer")["ok"]
        assert entry["id"] in {row["id"] for row in peer.call("whiteboard.list", {"id": thread})["items"]}
        assert public_notes_equal(peer.call("get_thread", {"id": thread}), "")
        assert client.call("room.sync", operation="room-sync-owner")["ok"]
        assert len(client.call("room.status")["peers"]) == 1
    return server_sync_checks(client, root, thread)


def server_sync_checks(client, root, thread):
    server_root, files = root / "sync-server", root / "sync-originals"
    files.mkdir()
    original = files / "retained.txt"
    original.write_bytes(b"Owned loopback sync original")
    expected = digest(original.read_bytes())
    init = subprocess.run([sys.executable, "-m", "threaddesk.server_sync.cli", "init", "--data-dir", str(server_root),
                           "--user", "acceptance"], env=client.env, capture_output=True, text=True, timeout=30)
    assert init.returncode == 0 and 20 <= len(init.stdout.strip()) <= 256
    token = init.stdout.strip()
    # This flag exists only in the isolated child CLI environment, never in a
    # persistent user setting or the parent environment.
    client.env["THREADDESK_SYNC_ALLOW_HTTP"] = "1"
    with loopback_server(root, client.env, sync_data=server_root) as url:
        revision = client.call("get_thread", {"id": thread})["revision"]
        client.call("server_sync.configure", {"thread_id": thread, "url": url, "project_id": "", "root": str(files),
            "token": token, "automatic": False, "offline_enabled": True}, operation="sync-configure", revision=revision)
        first = client.call("server_sync.run", {"thread_id": thread}, operation="sync-run", revision=revision)
        assert first["state"] == "ready"
        status = client.call("server_sync.status", {"thread_id": thread})
        assert status["configured"] and "token" not in status
        base = url + "/api/projects/" + status["project_id"]
        remote, _ = http_get(base + "/thread", token)
        assert json.loads(remote)["context"]["notes"] == "OwnerLocalNeedle preserved notes"
        listing, _ = http_get(base + "/files", token)
        assert any(row["path"] == original.name for row in json.loads(listing)["files"])
        revision = client.call("get_thread", {"id": thread})["revision"]
        client.call("server_sync.offline", {"thread_id": thread, "enabled": False}, operation="sync-offline", revision=revision)
        assert client.call("server_sync.run", {"thread_id": thread}, operation="sync-metadata", revision=revision)["state"] == "metadata_only"
        revision = client.call("get_thread", {"id": thread})["revision"]
        lifecycle = client.call("server_sync.lifecycle_sync", {"thread_id": thread}, operation="sync-lifecycle", revision=revision)
        assert lifecycle["mode"] == "lifecycle_metadata" and lifecycle["files_transferred"] is False
        assert client.call("server_sync.status", {"thread_id": thread})["status"]["mode"] == "lifecycle_metadata"
        assert digest(original.read_bytes()) == expected
    client.env.pop("THREADDESK_SYNC_ALLOW_HTTP", None)
    return {"rooms_actual_http": True, "server_sync_actual_http": True, "original_sha256": expected,
            "loopback_dev_flag_process_only": True, "ui_startup_probe_and_background_workers": "lifespan disabled; not claimed tested"}


def call_summaries(clients):
    return [{"workspace": call["request"]["workspace_id"], "command": call["command"], "exit_code": call["exit_code"],
             "ok": call["response"].get("ok"), "code": call["response"].get("code"),
             "operation_id": call["request"].get("operation_id"), "elapsed_ms": call["elapsed_ms"],
             "request_sha256": digest(call["request"]), "response_sha256": digest(call["response"])}
            for client in clients for call in client.calls]


def run(root, binary=None, *, network=True):
    clients, proof, phase = [], {}, "initialization"
    report = {"fixture_only": True, "workshop_excluded": True,
              "principal_identity": "must come from actual bridge task receipt",
              "provider_boundary": "no model invocation or provider success claimed",
              "command_binary": str(binary) if binary else None, "workspace_backend": "json",
              "fresh_process_per_command": True}
    try:
        client = Client(root, binary)
        clients.append(client)
        report["runtime_build"] = client.call("library_query", {"action": "status"})["build"]
        specs = catalogue(client)
        created = client.call("thread_manage", {"action": "create", "data": {"title": "Operations acceptance"}},
                              operation="thread-create", revision=0)["thread"]
        thread = created["id"]
        client.call("thread_manage", {"action": "set_note", "id": thread, "data": {"text": "OwnerLocalNeedle preserved notes"}},
                    operation="thread-note", revision=created["revision"])
        project = client.call("graph.node.create", {"kind": "project", "title": "Operations project", "visibility": "shared"},
                              operation="project-create", revision=0)["id"]
        checks = [("actors", lambda: actor_checks(client)), ("modules", lambda: module_checks(client, thread, project)),
                  ("gate_search", lambda: gate_and_search(client, thread, specs)),
                  ("partial_import_resume", lambda: resume_import(client, root, thread)),
                  ("exports", lambda: exports(client, project)),
                  ("backup_profiles", lambda: backup_and_profiles(client, thread))]
        for phase, action in checks:
            print("Checking " + phase, file=sys.stderr, flush=True)
            proof[phase] = action()
        phase = "loopback_network"
        if network:
            print("Checking " + phase, file=sys.stderr, flush=True)
            proof[phase] = network_checks(client, root, thread, proof["exports"], clients)
        else:
            report["network_boundary"] = "explicitly omitted; no network success claimed"
        report["ok"] = True
    except Exception as exc:
        report.update(ok=False, failure_phase=phase, failure_type=type(exc).__name__)
    finally:
        report["proof"] = proof
        report["calls"] = call_summaries(clients)
        # Request files can contain fixture credentials. Keep no plaintext
        # envelope after the child process has exited.
        for client in clients:
            request_path = client.root / "request.json"
            if request_path.exists():
                request = json.loads(request_path.read_text())
                if not client.calls or digest(client.calls[-1]["request"]) != digest(request):
                    report.setdefault("unconfirmed_attempts", []).append({
                        "command": request.get("command"), "operation_id": request.get("operation_id"),
                        "workspace": request.get("workspace_id"), "request_sha256": digest(request),
                        "safe_to_repeat": False})
                request_path.unlink()
        path = root / "workspace-operations-result.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        path.chmod(0o600)
    print(json.dumps({"ok": report["ok"], "calls": len(report["calls"]), "fixture_only": True,
                      "failure_phase": report.get("failure_phase"), "failure_type": report.get("failure_type"), "report": str(path)}))
    return 0 if report["ok"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, help="New private fixture directory; must not exist")
    parser.add_argument("--command-binary")
    parser.add_argument("--without-network", action="store_true", help="Explicitly omit loopback network acceptance")
    args = parser.parse_args()
    root = Path(args.directory).resolve()
    root.mkdir(mode=0o700)
    return run(root, args.command_binary, network=not args.without_network)


if __name__ == "__main__":
    raise SystemExit(main())
