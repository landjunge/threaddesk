"""Owned 275-file transport and live-source acceptance through public commands.

With --command-binary this exercises the frozen desktop backend and its worker.
All data and receipts remain under the explicitly supplied private test directory.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", required=True)
    parser.add_argument("--command-binary")
    args = parser.parse_args()
    root = Path(args.directory).resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if any(root.iterdir()):
        raise RuntimeError("Use an empty owned test directory")
    source, workspace = root / "source", root / "workspace"
    source.mkdir()
    for number in range(275):
        (source / f"document-{number:03}.txt").write_text(f"Source file {number} acceptance\n")
    os.environ.update(THREADDESK_HOME=str(workspace), THREADDESK_STORAGE="json")
    evidence = []

    def command(action, **fields):
        request = {"action": action, **fields}
        front = ([args.command_binary, "--library-command"] if args.command_binary else
                 [sys.executable, "-m", "threaddesk.ui.cli", "library", "--request"])
        result = subprocess.run([*front, json.dumps(request)], text=True, capture_output=True,
                                timeout=120, check=False)
        payload = json.loads(result.stdout)
        assert result.returncode == 0 and payload.get("ok"), (payload, result.stderr)
        size = len(result.stdout.encode())
        assert size < 65536, (action, size)
        evidence.append({"request": request, "response_bytes": size, "response": payload})
        return payload["result"]

    job = command("import", operation_id="large-acceptance-import", data={"source": str(source)})
    assert job["complete"] and job["total"] == 275, job
    assert command("status")["counts"]["records"] == 275
    seen, offset = set(), 0
    while offset is not None:
        page = command("import_status", operation_id="large-acceptance-import", offset=offset, limit=20)
        seen.update(row["record_id"] for row in page["files"])
        offset = page["next_offset"]
    assert len(seen) == 275
    command("operation", operation_id="large-acceptance-import")
    identity = job["files"][0]["record_id"]
    original = source / job["files"][0]["original_path"]
    info = command("info", id=identity)
    renamed = command("rename", id=identity, operation_id="source-user-rename", expected_revision=info["revision"],
                      data={"filename": "UserName.txt"})["record"]
    command("move", id=identity, operation_id="source-user-move", expected_revision=renamed["revision"],
            data={"folder": "UserFolder"})
    log = (root / "backend.log").open("w")
    if args.command_binary:
        backend = [args.command_binary]
    else:
        backend = [sys.executable, "-c", (
            "import sys; from threaddesk.services.library_runtime import LibraryRuntime; "
            "from threaddesk.api.service import ThreadService; "
            "worker=LibraryRuntime(lambda: ThreadService().store); worker.start(); "
            "print('THREADDESK_URL source-worker',flush=True); sys.stdin.buffer.read(1); worker.stop()")]
    process = subprocess.Popen(backend, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, text=True)
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            assert selector.select(timeout=30), "Backend startup timed out"
            ready = process.stdout.readline().strip()
        assert ready.startswith("THREADDESK_URL "), ready

        def wait_for(predicate):
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                assert process.poll() is None, "Backend exited"
                result = command("sources")
                if predicate(result["watches"][0]):
                    return result
                time.sleep(1)
            raise AssertionError("Live source did not converge")

        wait_for(lambda watch: watch["status"] == "ready")
        before = command("sources")["watches"][0]["fingerprint"]
        original.write_text("CurrentSourceNeedle source version 2\n")
        (source / "new-file.txt").write_text("FreshAddedNeedle new file\n")
        wait_for(lambda watch: watch["status"] == "ready" and watch["fingerprint"] != before)
        hit = next(row for row in command("search", query="CurrentSourceNeedle")["hits"]
                   if row.get("entity_type") == "file")
        current = command("info", id=hit["record_id"])
        assert current["filename"] == "UserName.txt" and current["logical_path"] == "UserFolder/UserName.txt"
        assert current["current_version"] and current["predecessor_record_id"] == identity
        assert not command("info", id=identity)["current_version"]
        assert command("search", query="FreshAddedNeedle")["hits"]
        trashed = command("trash", id=current["id"], operation_id="source-current-trash",
                          expected_revision=current["revision"], data={})["record"]
        restored = command("restore", id=current["id"], operation_id="source-current-restore",
                           expected_revision=trashed["revision"],
                           data={"trash_generation": trashed["trash_generation"]})["record"]
        assert restored["id"] == current["id"] and not restored["trashed"]
        assert command("operation", operation_id="source-current-restore")["found"]
        assert command("search", query="CurrentSourceNeedle")["hits"]
        before = command("sources")["watches"][0]["fingerprint"]
        original.unlink()
        status = wait_for(lambda watch: watch["fingerprint"] != before and watch["missing_sources_count"] > 0)
        assert status["watches"][0]["missing_sources"][0]["stored_copy_not_deleted_by_watch"]
        assert command("search", query="CurrentSourceNeedle")["hits"]
        assert "CurrentSourceNeedle" in command("preview", id=current["id"])["text"]
    finally:
        if process.stdin:
            process.stdin.close()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=10)
        log.close()
    # A fresh process must still find the retained source snapshot after shutdown.
    assert command("search", query="CurrentSourceNeedle")["hits"]
    report = {"fixture_only": True, "initial_files": 275, "traversed_files": len(seen),
              "automatic_source_refresh": True, "preserved_user_overrides": True,
              "missing_source_retained": True, "commands": evidence}
    (root / "live-result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({"ok": True, "commands": len(evidence), "files": len(seen),
                      "max_response_bytes": max(row["response_bytes"] for row in evidence),
                      "automatic_source_refresh": True, "report": str(root / "live-result.json")}))


if __name__ == "__main__":
    main()
