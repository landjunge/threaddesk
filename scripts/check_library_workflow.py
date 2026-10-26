"""Exercise public CLI commands against owned synthetic data, optionally opening TXT.

Run through the authorized visible KiraBridge terminal for transport evidence.
This is not a replacement for the independent browser or principal checks.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", required=True)
    parser.add_argument("--command-binary")
    parser.add_argument("--open-text", action="store_true")
    args = parser.parse_args()
    root = Path(args.directory).resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    marker = root / "owned-library-workflow.json"
    if any(root.iterdir()) and not marker.exists():
        raise RuntimeError("Refusing an unowned test directory")
    state = json.loads(marker.read_text()) if marker.exists() else {}
    workspace, source = root / "workspace", root / "source"
    os.environ.update(THREADDESK_HOME=str(workspace), THREADDESK_STORAGE="json")
    source.mkdir(exist_ok=True)
    original = source / "ThreadDesk-BridgeTest.txt"
    initial = "ThreadDesk synthetic acceptance: Brückenpfeiler ContentAnchor42\n"
    if not original.exists():
        original.write_text(initial, encoding="utf-8")
        (source / "structured.json").write_text('{"value":"SecondAnchor"}', encoding="utf-8")
        (source / "unknown.threadtest").write_bytes(b"unrecognized managed data")
    from threaddesk.api.service import ThreadService
    from threaddesk.core.models import KnowledgeNode
    svc = ThreadService()
    if not state:
        thread = svc.create("ThreadDesk Library Acceptance")
        svc.store.save_node(KnowledgeNode(id="dddddddddddd", kind="project", title="Library Acceptance",
                                         metadata={"thread_id": thread.id}))
        state = {"thread_id": thread.id, "node_id": "dddddddddddd"}
        marker.write_text(json.dumps(state))
    evidence = []

    def command(action, *, expected_error=None, **fields):
        request = {"action": action, **fields}
        argv = ([args.command_binary, "--library-command"] if args.command_binary else
                [sys.executable, "-m", "threaddesk.ui.cli", "library", "--request"])
        completed = subprocess.run([*argv, json.dumps(request)], capture_output=True, text=True, timeout=60, check=False)
        result = json.loads(completed.stdout)
        if expected_error:
            assert completed.returncode == 2 and result.get("code") == expected_error, result
        else:
            assert completed.returncode == 0 and result.get("ok"), (result, completed.stderr)
        evidence.append({"action": action, "request": request, "exit_code": completed.returncode,
                         "response": result})
        return result.get("result", result)

    imported = command("import", operation_id="acceptance-import", data={"source": str(source), "thread_id": state["thread_id"]})
    assert imported["complete"], imported
    record_id = next(row["record_id"] for row in imported["files"] if row["original_path"].endswith("BridgeTest.txt"))
    command("import_status", operation_id="acceptance-import")
    command("sources")
    command("status")
    assert len(command("formats")) >= 40
    for query in ("BridgeTest", "ContentAnchor42", "brueckenpfeiler"):
        hits = command("search", query=query, project_id=state["node_id"])["hits"]
        assert any(row.get("record_id") == record_id for row in hits), hits
    assert any(row["id"] == record_id for row in command("list", node_id=state["node_id"])["records"])
    preview = command("preview", id=record_id)
    assert preview["kind"] == "text" and "ContentAnchor42" in preview["text"]
    info = command("info", id=record_id)
    assert info["sha256"] == hashlib.sha256(original.read_bytes()).hexdigest()
    if args.open_text:
        opened = command("open", id=record_id, operation_id="acceptance-open", expected_revision=info["revision"])
        assert opened["status"] == "launch_requested", opened
        assert opened["application"].endswith(".app") and not opened["human_read_confirmed"]
        readback = command("operation", operation_id="acceptance-open")
        assert readback["found"] and readback["result"]["sha256"] == info["sha256"]
    copied = command("copy", id=record_id, operation_id="acceptance-copy", expected_revision=info["revision"],
                     data={"filename": "Copied.txt"})
    assert copied["record"]["sha256"] == info["sha256"]
    command("info", id=copied["record"]["id"])
    renamed = command("rename", id=record_id, operation_id="acceptance-rename", expected_revision=info["revision"],
                      data={"filename": "Renamed.txt"})
    command("info", id=record_id)
    moved = command("move", id=record_id, operation_id="acceptance-move", expected_revision=renamed["record"]["revision"],
                    data={"folder": "Checked"})
    assigned = command("assign", id=record_id, operation_id="acceptance-assign", expected_revision=moved["record"]["revision"],
                       data={"node_ids": [state["node_id"]]})
    command("list", node_id=state["node_id"], folder="Checked")
    assert command("search", query="Renamed")["hits"]
    trashed = command("trash", id=record_id, operation_id="acceptance-trash", expected_revision=assigned["record"]["revision"], data={})
    assert command("preview", id=record_id)["record"]["trashed"]
    assert not command("search", query="Renamed")["hits"]
    restored = command("restore", id=record_id, operation_id="acceptance-restore", expected_revision=trashed["record"]["revision"],
                       data={"trash_generation": trashed["record"]["trash_generation"]})
    assert restored["record"]["id"] == record_id
    assert command("search", query="Renamed")["hits"]
    command("operation", operation_id="acceptance-restore")
    unknown_id = next(row["record_id"] for row in imported["files"] if row["original_path"].endswith("threadtest"))
    unknown = command("preview", id=unknown_id)
    assert unknown["kind"] == "metadata" and not unknown["can_open"]
    command("open", id=unknown_id, operation_id="acceptance-blocked-open", expected_revision=1, expected_error="external_open_blocked")
    command("refresh_sources", operation_id="acceptance-source-poll")
    command("sources")
    assert original.read_text(encoding="utf-8") == initial
    report = {"fixture_only": True, "record_id": record_id, "commands": evidence,
              "actual_mac_open_requested": args.open_text, "original_preserved": True,
              "principal_identity": "must be taken from the actual KiraBridge task receipt"}
    (root / "workflow-result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({"ok": True, "commands": len(evidence), "record_id": record_id,
                      "original_preserved": True, "mac_open": args.open_text,
                      "report": str(root / "workflow-result.json")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
