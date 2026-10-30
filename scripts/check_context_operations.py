"""Actual local CLI acceptance for context, handoff and return administration.

Fixture claims are never evidence of a model run, remote delivery or principal.
Every command runs through the existing fresh-process Client. Reports contain
only IDs, hashes, statuses and explicit limits, without context/history bodies.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import io
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from check_workspace_commands import Client
from check_workspace_operations import call_summaries, digest


def thread(client, identity):
    return client.call("get_thread", {"id": identity})


def legacy_context(client):
    created = client.call("thread_manage", {"action": "create", "data": {"title": "Local context fixture"}},
                          operation="context-create", revision=0)["thread"]
    identity = created["id"]
    assert client.call("current_thread")["id"] == identity
    assert identity in {row["id"] for row in client.call("list_threads", {"include_archived": True})}
    other = client.call("thread_manage", {"action": "create", "data": {"title": "Other local fixture"}},
                        operation="context-other", revision=0)["thread"]
    switched = client.call("switch_thread", {"id": identity}, operation="context-switch", revision=created["revision"])
    assert switched["id"] == client.call("current_thread")["id"] == identity
    client.call("switch_thread", {"id": identity}, operation="context-switch", revision=created["revision"])
    current = thread(client, identity)
    note = {"id": identity, "text": "ContextAcceptanceNeedle retained local note"}
    changed = client.call("add_note", note, operation="legacy-note", revision=current["revision"])
    assert "ContextAcceptanceNeedle" in changed["notes"]
    client.call("add_note", note, operation="legacy-note", revision=current["revision"])
    client.call("add_note", {**note, "text": "Different fixture"}, operation="legacy-note",
                revision=current["revision"], error="operation_conflict")
    client.call("add_note", note, operation="legacy-note-stale", revision=current["revision"], error="revision_conflict")
    saved = client.call("save_snapshot", {"id": identity, "label": "Local context snapshot"},
                        operation="legacy-snapshot", revision=changed["revision"])
    assert saved["id"] in {row["id"] for row in client.call("list_snapshots", {"id": identity})}
    current = thread(client, identity)
    temporary = client.call("add_note", {"id": identity, "text": "TemporaryContextMarker"},
                            operation="legacy-temporary", revision=current["revision"])
    restored = client.call("restore_snapshot", {"snap_id": saved["id"]},
                           operation="legacy-restore", revision=temporary["revision"])
    assert "ContextAcceptanceNeedle" in restored["notes"] and "TemporaryContextMarker" not in restored["notes"]
    prompt = client.call("prompt.preview", {"id": identity, "target": "generic", "variant": "short"})
    assert "ContextAcceptanceNeedle" in prompt["text"]
    assert thread(client, identity)["revision"] == restored["revision"]
    args = {"id": identity, "target": "generic", "variant": "short", "save": True}
    saved_prompt = client.call("generate_prompt", args, operation="legacy-prompt-save", revision=restored["revision"])
    client.call("generate_prompt", args, operation="legacy-prompt-save", revision=restored["revision"])
    assert thread(client, identity)["revision"] == restored["revision"] + 1
    backup = client.call("backup.create", operation="context-readback-backup")
    body = Path(backup["path"]).read_bytes()
    assert digest(body) == backup["sha256"]
    with ZipFile(io.BytesIO(body)) as archive:
        matches = [name for name in archive.namelist() if name.endswith("threads/" + identity + ".json")]
        assert len(matches) == 1
        copied = json.loads(archive.read(matches[0]))
        prompts = copied["context"]["prompts"]
        assert len(prompts) == 1 and prompts[0]["text"] == saved_prompt["text"]
    assert client.call("check_gate", {"id": identity, "action": "handoff"})["allow"]
    board = client.call("dashboard", operation="context-dashboard")
    files = [Path(board[key]) for key in ("path", "html_path")]
    assert all(path.is_relative_to(client.workspace) and path.is_file() for path in files)
    return identity, {"thread_id": identity, "other_thread_id": other["id"], "snapshot_id": saved["id"],
        "prompt_sha256": digest(saved_prompt["text"].encode()), "saved_prompt_count": len(prompts),
        "backup_sha256": backup["sha256"], "dashboard_sha256": [digest(path.read_bytes()) for path in files],
        "legacy_replay_conflict_stale_and_readback": True}


def knowledge_context(client, identity):
    def manage(action, data, operation):
        current = thread(client, identity)
        return client.call("knowledge_manage", {"id": identity, "action": action,
            "data": {"source_ref": "fixture:local-context", "source_revision": operation, **data}},
            operation=operation, revision=current["revision"])
    first = manage("record", {"kind": "decision", "title": "Fixture decision", "status": "confirmed"}, "knowledge-record")["node"]
    replacement = manage("supersede", {"node_id": first["id"], "expected_node_revision": first["revision"],
                                     "title": "Fixture replacement"}, "knowledge-supersede")["node"]
    assert client.call("graph.node", {"id": first["id"]})["status"] == "superseded"
    question = manage("record", {"kind": "question", "title": "Fixture question", "status": "waiting"}, "knowledge-question")["node"]
    resolved = manage("resolve_question", {"node_id": question["id"], "expected_node_revision": question["revision"],
                                          "text": "Local fixture resolution"}, "knowledge-resolve")["node"]
    assert resolved["status"] == "done"
    manage("save_reentry", {"summary": "Local context summary fixture", "next_step": "Review local fixture"}, "knowledge-reentry")
    reentry = client.call("get_reentry", {"id": identity})
    assert reentry["saved"]["summary"] == "Local context summary fixture"
    assert reentry["saved"]["source_verification"] == "referenced_unverified"
    assert replacement["id"] in {row["id"] for row in reentry["decisions"]}
    assert question["id"] in {row["id"] for row in reentry["answered_questions"]}
    return {"decision_id": first["id"], "replacement_id": replacement["id"], "question_id": question["id"],
            "reentry_sha256": digest(reentry), "source_verification": "referenced_unverified", "no_work_started": True}


def local_packets(client, identity):
    current = thread(client, identity)
    handoff = client.call("export_handoff", {"id": identity, "target": "generic"},
                          operation="local-handoff", revision=current["revision"])
    assert handoff["ran"] is False and handoff["sent"] is False
    artifacts = [Path(handoff["path"])]
    assert json.loads(artifacts[0].read_text())["handoff_id"] == handoff["handoff_id"]
    client.call("export_handoff", {"id": identity, "target": "generic"},
                operation="local-handoff", revision=current["revision"])
    packets = {}
    for system in ("grok", "gnom"):
        packet = client.call("export_" + system, {"id": identity, "mode": "brainstorm", "variant": "short"},
                             operation="local-" + system, revision=current["revision"])
        assert packet["ran"] is False
        if system == "gnom":
            assert packet["sent"] is False
        for key in ("path", "prompt_path", "chat_path"):
            if key in packet:
                path = Path(packet[key]);assert path.is_relative_to(client.workspace) and path.is_file()
                artifacts.append(path)
        packets[system] = packet
    # This registers a local fixture claim. It neither contacts nor starts Gnom.
    bound = client.call("bind_gnom_job", {"job_id": "fixture-local-job", "packet": packets["gnom"]}, operation="local-gnom-bind")
    assert bound["job_id"] == "fixture-local-job"
    client.call("bind_gnom_job", {"job_id": "fixture-local-job", "packet": packets["gnom"]}, operation="local-gnom-bind")
    assert any(row["job_id"] == "fixture-local-job" for row in client.call("list_gnom_jobs"))
    # Exercise local callback intake with an explicit blocked fixture claim;
    # never manufacture a started/delivered callback as real hub evidence.
    callback = {"format": "threaddesk.gnom-callback.v1", "event_id": "fixture-blocked", "job_id": bound["job_id"],
        "handoff_revision": bound["handoff_revision"], "status": "blocked", "occurred_at": datetime.now(timezone.utc).isoformat(),
        "details": "Local acceptance fixture only; no real hub interaction"}
    received = client.call("receive_gnom_callback", {"payload": callback}, operation="local-blocked-callback")
    assert received["job"]["status"] == "blocked" and received["return"] is None
    client.call("receive_gnom_callback", {"payload": callback}, operation="local-blocked-callback")
    client.call("receive_gnom_callback", {"payload": {**callback, "status": "error"}},
                operation="local-blocked-callback", error="operation_conflict")
    assert next(row for row in client.call("list_gnom_jobs") if row["job_id"] == bound["job_id"])["status"] == "blocked"
    assert client.call("gate.status")["today"]["execute"] == 0
    return {"handoff_id": handoff["handoff_id"], "local_job_id": bound["job_id"],
            "artifact_sha256": [digest(path.read_bytes()) for path in artifacts],
            "ran": False, "sent": False, "fixture_callback_status": "blocked", "external_hub_delivery": "not_performed"}


def issued_and_returned(client, identity):
    current = thread(client, identity)
    args = {"id": identity, "target": "generic"}
    handoff = client.call("issue_handoff", args, operation="issued-context", revision=current["revision"])
    assert handoff["ran"] is False and handoff["sent"] is False
    assert client.call("issue_handoff", args, operation="issued-context", revision=current["revision"])["handoff_id"] == handoff["handoff_id"]
    client.call("issue_handoff", {**args, "target": "codex"}, operation="issued-context",
                revision=current["revision"], error="operation_conflict")
    fetched = client.call("get_issued_handoff", {"operation_id": "issued-context"})
    assert fetched["found"] and fetched["issued"]["handoff"]["handoff_id"] == handoff["handoff_id"]
    binding = {"handoff_id": handoff["handoff_id"], "handoff_revision": handoff["revision"],
        "task_id": handoff["task_id"], "bridge_task_id": "fixture-no-remote-task", "run_id": "fixture-local-run",
        "worker": "fixture-local-worker", "expected_thread_revision": handoff["source"]["thread_revision"],
        "principal_ref": "fixture-claim-not-authentication", "operator_scope": "isolated-context-fixture",
        "request_hash": digest({"fixture": True, "handoff_id": handoff["handoff_id"]})}
    client.call("bind_handoff_run", binding, operation="bind-local-run")
    client.call("bind_handoff_run", binding, operation="bind-local-run")
    client.call("bind_handoff_run", {**binding, "run_id": "different-local-fixture"},
                operation="bind-local-conflict", error="binding_conflict")
    common = {"handoff_id": handoff["handoff_id"], "handoff_revision": handoff["revision"],
              "run_id": binding["run_id"], "question_id": "local-question"}
    question = {**common, "text": "Local fixture question, no adapter dispatch"}
    asked = client.call("record_handoff_question", question, operation="local-question")
    assert asked["question"]["status"] == "awaiting_answer"
    client.call("record_handoff_question", question, operation="local-question")
    client.call("record_handoff_question", {**common, "text": "Different question"},
                operation="question-domain-conflict", error="question_conflict")
    answer = {**common, "answer_id": "local-answer", "text": "Local fixture answer"}
    answered = client.call("answer_handoff_question", answer, operation="local-answer")
    assert answered["delivery_status"] == "recorded_for_run"
    client.call("answer_handoff_question", answer, operation="local-answer")
    client.call("answer_handoff_question", {**answer, "answer_id": "other-answer"},
                operation="answer-domain-conflict", error="answer_conflict")
    board = client.call("whiteboard.list", {"id": identity})["items"]
    bound_rows = [row for row in board if row.get("run_id") == binding["run_id"]]
    assert len(bound_rows) == 2 and all(row["metadata"]["adapter_delivery_verified"] is False for row in bound_rows)
    payload = {"format": "threaddesk.return.v1", "return_id": "local-fixture-return", "handoff_id": handoff["handoff_id"],
        "handoff_revision": handoff["revision"], "thread_id": identity, "task_id": handoff["task_id"],
        "worker": binding["worker"], "run_id": binding["run_id"], "result": "Fixture payload, not an agent result",
        "files": [], "pull_request": None, "test_results": [], "open_issues": ["Fixture only; no external validation"],
        "delivery_status": "delivered", "review_status": "unverified", "created_at": datetime.now(timezone.utc).isoformat()}
    returned = client.call("import_return", {"payload": payload, "strict_binding": True}, operation="local-return")
    assert returned["binding_status"] == "issued_bound" and returned["decision"] is None
    assert returned["return"]["review_status"] == "unverified"
    client.call("import_return", {"payload": payload, "strict_binding": True}, operation="local-return")
    exact = client.call("get_return", {"return_id": payload["return_id"]})
    assert exact["found"] and exact["item"]["decision"] is None
    assert any(row["return"]["return_id"] == payload["return_id"] for row in client.call("list_returns"))
    reviewed = client.call("review_return", {"return_id": payload["return_id"], "choice": "rework", "note": "Local fixture review"},
                           operation="local-review")
    assert reviewed["decision"]["choice"] == "rework"
    client.call("review_return", {"return_id": payload["return_id"], "choice": "rework", "note": "Local fixture review"},
                operation="local-review")
    readback = client.call("get_return", {"return_id": payload["return_id"]})
    assert readback["item"]["decision"]["choice"] == "rework"
    assert client.call("gate.status")["today"]["execute"] == 0
    return {"handoff_id": handoff["handoff_id"], "run_id": binding["run_id"], "return_id": payload["return_id"],
            "question_id": common["question_id"], "answer_id": answer["answer_id"], "review_choice": "rework",
            "adapter_delivery_verified": False, "model_identity_verified": False, "payload_fixture_only": True,
            "return_sha256": digest(payload), "readback_sha256": digest(readback)}


def local_bundle_from_export(client, root):
    node = client.call("graph.node.create", {"kind": "project", "title": "Local exported migration fixture",
        "details": "Migration fixture exported through CLI", "visibility": "shared"}, operation="migration-source", revision=0)
    exported = client.call("export.write", {"node_ids": [node["id"]], "format": "json"}, operation="migration-local-export")
    body = Path(exported["path"]).read_bytes();assert digest(body) == exported["sha256"]
    source = json.loads(body)["nodes"][0]
    text = ("# " + source["title"] + "\n\n" + source["details"] + "\n").encode()
    item = {"source_id": "fixture-export-project", "title": source["title"], "source_path": "local-fixture/project",
        "source_url": "fixture://local-cli-export/project", "source_type": "page", "parent_id": None,
        "last_edited_at": datetime.now(timezone.utc).isoformat(), "properties": {"status": "active"},
        "content_path": "content/local-project.md", "content_sha256": digest(text), "archived": False,
        "suggested_kind": "project", "mapping_reason": "Local fixture repackaged from CLI export, not an external Notion export"}
    members = {"objects.ndjson": (json.dumps(item) + "\n").encode(), "relations.ndjson": b"",
               "exclusions.json": b"[]\n", "report.md": b"# Local fixture only\nNo external system was accessed.\n",
               "content/local-project.md": text}
    manifest = {"format": "threaddesk-notion-bundle-v1", "schema_version": 1, "export_id": "local-cli-fixture-export",
        "created_at": datetime.now(timezone.utc).isoformat(), "source_workspace_id": "local-fixture-not-external",
        "roots": [item["source_id"]], "counts": {"objects": 1, "relations": 0, "content": 1, "attachments": 0, "exclusions": 0},
        "files": {name: {"size": len(value), "sha256": digest(value)} for name, value in members.items()}}
    path = root / "local-export-fixture.tdbundle"
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        for name, value in members.items():archive.writestr(name, value)
    path.chmod(0o600)
    return path, exported["sha256"]


def migration_checks(client, root, binary, clients):
    bundle, export_sha = local_bundle_from_export(client, root)
    preview = client.call("migration.preview", {"path": str(bundle)})
    assert preview["bundle_sha256"] == digest(bundle.read_bytes())
    # The export's original node still exists here; duplicate protection may
    # correctly block importing the same content back into its own source.
    client.call("migration.stage", {"path": str(bundle)}, operation="json-stage-denied", error="unsupported_backend")
    sqlite_root = root / "migration";sqlite_root.mkdir(mode=0o700)
    sqlite = Client(sqlite_root, binary);clients.append(sqlite)
    sqlite.env["THREADDESK_STORAGE"] = "sqlite"
    sqlite.workspace_id = sqlite.catalog()["workspace_id"]
    empty_preview = sqlite.call("migration.preview", {"path": str(bundle)})
    assert empty_preview["can_confirm_import"] and not empty_preview["blockers"]
    assert empty_preview["bundle_sha256"] == preview["bundle_sha256"]
    staged = sqlite.call("migration.stage", {"path": str(bundle)}, operation="migration-stage")
    assert staged["review_sha256"] == preview["bundle_sha256"] and staged["can_confirm_import"]
    assert sqlite.call("graph.query", {"limit": 10})["nodes"] == []
    args = {"bundle_sha256": staged["review_sha256"], "confirmation": "import_reviewed_bundle"}
    committed = sqlite.call("migration.commit", args, operation="migration-commit")
    assert committed["status"] == "committed"
    sqlite.call("migration.commit", args, operation="migration-commit")
    sqlite.call("migration.commit", {**args, "bundle_sha256": "0" * 64}, operation="migration-commit", error="operation_conflict")
    imported = sqlite.call("graph.query", {"limit": 10})["nodes"]
    assert len(imported) == 1 and imported[0]["title"] == "Local exported migration fixture"
    recovered = sqlite.call("migration.recover", {"batch_id": committed["id"]}, operation="migration-recover")
    recovery = Path(recovered["recovery_path"])
    assert recovery.is_relative_to(sqlite.workspace) and recovery.is_dir()
    read_root = root / "recovery-readback";read_root.mkdir(mode=0o700)
    reader = Client(read_root, binary);clients.append(reader)
    reader.env.update(THREADDESK_HOME=str(recovery), THREADDESK_STORAGE="sqlite")
    reader.workspace_id = reader.catalog()["workspace_id"]
    assert reader.call("graph.query", {"limit": 10})["nodes"] == []
    assert len(sqlite.call("graph.query", {"limit": 10})["nodes"]) == 1
    assert digest(bundle.read_bytes()) == preview["bundle_sha256"]
    return {"source": "local CLI export repackaged as a valid fixture; no Notion/remote export claimed",
            "export_sha256": export_sha, "bundle_sha256": preview["bundle_sha256"], "batch_id": committed["id"],
            "imported_node_id": imported[0]["id"], "sqlite_commit_replay_and_recovery_readback": True,
            "source_preview_blockers": preview["blockers"], "json_write_boundary": "unsupported_backend",
            "live_workspace_preserved_by_recovery": True}


def run(root, binary=None, *, migration=True):
    clients, proof, phase = [], {}, "initialization"
    report = {"fixture_only": True, "principal_identity": "take only from actual bridge receipt",
        "provider_boundary": "no agent starts, model calls or external deliveries; local fixture claims only",
        "workshop_excluded": True, "fresh_process_per_command": True, "command_binary": binary,
        "script_sha256": digest(Path(__file__).read_bytes())}
    try:
        client = Client(root, binary);clients.append(client)
        client.env["THREADDESK_SOURCE_ROOTS"] = "[]"
        report["runtime_build"] = client.call("library_query", {"action": "status"})["build"]
        client.call("gate.set", {"cooldown_seconds": 0}, operation="context-gate")
        phase = "legacy_context";print("Checking " + phase, flush=True)
        identity, proof[phase] = legacy_context(client)
        for phase, action in (("knowledge_context", lambda: knowledge_context(client, identity)),
                              ("local_packets", lambda: local_packets(client, identity)),
                              ("issued_questions_returns", lambda: issued_and_returned(client, identity))):
            print("Checking " + phase, flush=True);proof[phase] = action()
        if migration:
            phase = "local_sqlite_migration";print("Checking " + phase, flush=True)
            proof[phase] = migration_checks(client, root, binary, clients)
        else:
            report["migration_boundary"] = "explicitly omitted; no migration success claimed"
        report["ok"] = True
    except Exception as exc:
        report.update(ok=False, failure_phase=phase, failure_type=type(exc).__name__, failure_sha256=digest(str(exc).encode()))
    finally:
        report["proof"] = proof;report["calls"] = call_summaries(clients)
        for client in clients:
            path = client.root / "request.json"
            if path.exists():
                request = json.loads(path.read_text())
                if not client.calls or digest(request) != digest(client.calls[-1]["request"]):
                    report.setdefault("unconfirmed_attempts", []).append({"command": request.get("command"),
                        "operation_id": request.get("operation_id"), "request_sha256": digest(request), "safe_to_repeat": False})
                path.unlink()
        path = root / "context-operations-result.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2));path.chmod(0o600)
    print(json.dumps({"ok": report["ok"], "calls": len(report["calls"]), "fixture_only": True,
                      "failure_phase": report.get("failure_phase"), "failure_type": report.get("failure_type"), "report": str(path)}))
    return 0 if report["ok"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, help="A new private fixture directory that does not exist")
    parser.add_argument("--command-binary")
    parser.add_argument("--without-migration", action="store_true")
    args = parser.parse_args()
    root = Path(args.directory).resolve();root.mkdir(mode=0o700)
    binary = str(Path(args.command_binary).resolve(strict=True)) if args.command_binary else None
    return run(root, binary, migration=not args.without_migration)


if __name__ == "__main__":
    raise SystemExit(main())
