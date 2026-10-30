"""Exercise all existing library import adapters through fresh CLI processes.

Only owned fixtures are created. A private CLI is briefly paused during its
real blob copy to observe pending status, without editing store/journal data.
The report contains IDs, hashes, status and calls, never original texts/history.
Actual KiraBridge principal/task evidence belongs to the invoking bridge task.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from zipfile import ZIP_DEFLATED, ZipFile

from check_workspace_commands import Client


def digest(value):
    body = value if isinstance(value, bytes) else json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(body).hexdigest()


def file_digest(path):
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def paged(client, command, arguments, *, name="items", limit=1):
    rows, offset, pages = [], 0, 0
    while offset is not None:
        page = client.call(command, {**arguments, "limit": limit, "offset": offset})
        rows.extend(page[name])
        pages += 1
        next_offset = page["next_offset"]
        assert next_offset is None or next_offset > offset, "Pagination did not advance"
        assert pages <= 200, "Fixture pagination exceeded its budget"
        offset = next_offset
    return rows, pages


def replay(client, command, arguments, operation):
    result = client.call(command, arguments, operation=operation)
    repeated = client.call(command, arguments, operation=operation)
    assert client.calls[-1]["response"]["duplicate"] is True
    assert result == repeated, "Replay changed the confirmed domain result"
    status = client.call("command.operation", {"operation_id": operation})
    assert status["found"] and status["state"] == "complete" and status["result"] == result
    return result


def record_for(client, relative, wanted_hash, thread_id):
    rows, _ = paged(client, "library_query", {"action": "list"}, name="records", limit=50)
    matches = [row for row in rows if row["origin_path"] == relative and row["sha256"] == wanted_hash]
    assert len(matches) == 1, "Expected exactly one stored original version"
    saved = client.call("library_query", {"action": "info", "id": matches[0]["id"]})
    assert saved["sha256"] == wanted_hash and saved["thread_id"] == thread_id
    assert saved["integrity"] == "verified"
    return {"record_id": saved["id"], "thread_id": thread_id, "sha256": wanted_hash, "status": "verified"}


def pending_readback(client, source, relative, size):
    """Observe a real checkpoint, pausing only our copying CLI process group."""
    assert hasattr(os, "killpg") and hasattr(signal, "SIGSTOP"), "POSIX process pause is required"
    request = {"version": 1, "workspace_id": client.workspace_id, "command": "library.folder_import",
               "arguments": {"path": str(source)}, "operation_id": "legacy-pending-import"}
    request_file = client.root / "pending-import-request.json"
    request_file.write_text(json.dumps(request))
    request_file.chmod(0o600)
    argv = ([client.binary, "--command-file", str(request_file)] if client.binary else
            [sys.executable, "-m", "threaddesk.ui.cli", "command", "--request-file", str(request_file)])
    started = time.monotonic()
    blob_prefix = "." + file_digest(source / relative) + "."
    worker = subprocess.Popen(argv, env=client.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True, start_new_session=True)
    paused = False
    try:
        deadline = time.monotonic() + 45
        journal = client.workspace / "library-files" / "journal.json"
        blobs = client.workspace / "library-files" / "blobs"
        while time.monotonic() < deadline:
            assert worker.poll() is None, "Import completed before its pending checkpoint was observed"
            # Readiness checks are observation only. No journal, CAS or lock
            # fixture is fabricated; the CLI creates the checkpoint and partial.
            try:
                checkpoint = json.loads(journal.read_text()).get("items", {}).get(relative, {})
                copying = any(0 < path.stat().st_size < size for path in blobs.glob(blob_prefix + "*"))
            except (FileNotFoundError, ValueError, OSError):
                checkpoint, copying = {}, False
            if checkpoint.get("status") == "pending" and copying:
                assert os.getpgid(worker.pid) == worker.pid
                os.killpg(worker.pid, signal.SIGSTOP)
                paused = True
                break
            time.sleep(.002)
        assert paused, "Real pending-copy checkpoint was not observed"
        pending, pages = paged(client, "library.journal_status", {"collection": "pending"})
        assert any(row["relative_path"] == relative and row["status"] == "pending" for row in pending)
        beyond = client.call("library.journal_status", {"collection": "pending", "limit": 1, "offset": len(pending)})
        assert beyond["items"] == [] and beyond["next_offset"] is None
        outstanding, _ = paged(client, "library.journal_status", {"collection": "outstanding"})
        assert any(row["relative_path"] == relative for row in outstanding)
        os.killpg(worker.pid, signal.SIGCONT)
        paused = False
        output, error = worker.communicate(timeout=60)
        assert len(output.encode()) < 30000, "CLI response exceeded bridge page budget"
        response = json.loads(output)
        client.calls.append({"command": request["command"], "request": request,
                             "exit_code": worker.returncode, "response": response,
                             "elapsed_ms": round((time.monotonic() - started) * 1000, 1)})
        assert worker.returncode == 0 and response.get("ok"), "Pending import did not complete"
        status = client.call("command.operation", {"operation_id": request["operation_id"]})
        assert status["state"] == "complete" and status["result"] == response["result"]
        assert client.call("library.journal_status", {"collection": "pending", "limit": 1})["total"] == 0
        return {"status": "observed_and_completed", "pending_count": len(pending), "pages": pages}
    finally:
        if paused and worker.poll() is None:
            os.killpg(worker.pid, signal.SIGCONT)
        if worker.poll() is None:
            os.killpg(worker.pid, signal.SIGTERM)
            try:
                worker.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(worker.pid, signal.SIGKILL)
                worker.communicate(timeout=5)
        request_file.unlink(missing_ok=True)


def run(root, binary=None):
    client = Client(root, binary)
    originals, records = {}, []
    stage = "catalogue"
    try:
        catalogue, _ = paged(client, "command.catalog", {}, name="commands", limit=10)
        expected = {"library.folder_import", "library.journal_status", "library.journal_resume",
                    "library.selected_import", "library.package_import"}
        assert expected <= {row["id"] for row in catalogue}
        project = client.call("thread_manage", {"action": "create", "data": {"title": "Legacy import project"}},
                              operation="legacy-project", revision=0)["thread"]["id"]
        source = root / "owned-originals"
        folder = source / "Legacy import project"
        folder.mkdir(parents=True)

        def original(identity, path, body):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
            originals[identity] = {"path": path, "sha256": file_digest(path), "size": path.stat().st_size}
            return path

        first = original("folder-original", folder / "first.txt", b"Owned folder acceptance original\n")
        original("blocked-one", folder / "blocked.command", b"Synthetic inert unsupported fixture\n")
        original("blocked-two", folder / "blocked.exe", b"Synthetic inert unsupported fixture two\n")
        stage = "folder_import"
        imported = replay(client, "library.folder_import", {"path": str(source)}, "legacy-folder")
        assert imported["stored"] == 1 and imported["failed"] == 2
        records.append(record_for(client, "Legacy import project/first.txt", file_digest(first), project))
        stage = "journal_status"
        failures, failure_pages = paged(client, "library.journal_status", {"collection": "failures"})
        assert len(failures) == 2 and failure_pages == 2 and all(row["status"] == "failed" for row in failures)
        for number in range(3):
            original("fresh-" + str(number), folder / f"fresh-{number}.txt", f"Owned newly added original {number}\n".encode())
        outstanding, outstanding_pages = paged(client, "library.journal_status", {"collection": "outstanding"})
        assert len(outstanding) == 5 and outstanding_pages == 5
        assert client.call("library.journal_status", {"collection": "pending", "limit": 1})["total"] == 0
        stage = "journal_resume"
        resumed = replay(client, "library.journal_resume", {}, "legacy-resume")
        assert resumed["stored"] == 3 and resumed["failed"] == 2
        for number in range(3):
            path = folder / f"fresh-{number}.txt"
            records.append(record_for(client, "Legacy import project/" + path.name, file_digest(path), project))
        stage = "pending_checkpoint"
        large = folder / "pending-original.bin"
        chunk = bytes(range(256)) * 4096
        with large.open("xb") as stream:
            for _ in range(64):
                stream.write(chunk)
        originals["pending-original"] = {"path": large, "sha256": file_digest(large), "size": large.stat().st_size}
        pending = pending_readback(client, source, "Legacy import project/pending-original.bin", large.stat().st_size)
        records.append(record_for(client, "Legacy import project/pending-original.bin", file_digest(large), project))
        stage = "selected_import"
        selected = original("selected-original", root / "selected-originals" / "selected.txt", b"Owned selected acceptance original\n")
        selected_args = {"files": [{"name": "Legacy import project/selected.txt", "path": str(selected), "sha256": file_digest(selected)}]}
        imported = replay(client, "library.selected_import", selected_args, "legacy-selected")
        assert imported["stored"] == 1
        records.append(record_for(client, "Legacy import project/selected.txt", file_digest(selected), project))
        wrong = {"files": [{**selected_args["files"][0], "sha256": "0" * 64}]}
        client.call("library.selected_import", wrong, operation="legacy-selected", error="operation_conflict")
        client.call("library.selected_import", wrong, operation="legacy-selected-sha", error="artifact_conflict")
        stage = "package_import"
        package = root / "owned-package.zip"
        members = {"Legacy import project/package-a.txt": b"Owned ZIP package original A\n",
                   "Legacy import project/nested/package-b.txt": b"Owned ZIP package original B\n"}
        with ZipFile(package, "w", compression=ZIP_DEFLATED) as archive:
            for name, body in members.items():
                archive.writestr(name, body)
        originals["package-original"] = {"path": package, "sha256": file_digest(package), "size": package.stat().st_size}
        package_args = {"path": str(package), "sha256": file_digest(package)}
        imported = replay(client, "library.package_import", package_args, "legacy-package")
        assert imported["stored"] == 2
        for name, body in members.items():
            records.append(record_for(client, name, digest(body), project))
        client.call("library.package_import", {**package_args, "sha256": "0" * 64}, operation="legacy-package", error="operation_conflict")
        client.call("library.package_import", {**package_args, "sha256": "0" * 64}, operation="legacy-package-sha", error="artifact_conflict")
        stage = "original_readback"
        for item in originals.values():
            assert item["path"].is_file() and file_digest(item["path"]) == item["sha256"]
        report = {"ok": True, "fixture_only": True, "status": "passed", "workspace_id": client.workspace_id,
                  "command_binary_sha256": file_digest(Path(binary)) if binary else None,
                  "records": records, "originals": [{"fixture_id": identity, "sha256": value["sha256"],
                    "size": value["size"], "status": "preserved"} for identity, value in originals.items()],
                  "journal": {"failure_count": len(failures), "failure_pages": failure_pages,
                              "outstanding_count": len(outstanding), "outstanding_pages": outstanding_pages,
                              "pending": pending}, "bridge_principal_status": "requires_actual_invoking_task_receipt"}
    except Exception as exc:
        report = {"ok": False, "fixture_only": True, "status": "failed", "stage": stage,
                  "error_type": type(exc).__name__, "error_sha256": digest(str(exc))}
    report["calls"] = [{"command": call["command"], "operation_id": call["request"].get("operation_id"),
                         "exit_code": call["exit_code"], "status": "ok" if call["response"].get("ok") else call["response"].get("code"),
                         "request_sha256": digest(call["request"]), "response_sha256": digest(call["response"]),
                         "elapsed_ms": call["elapsed_ms"]} for call in client.calls]
    path = root / "legacy-imports-result.json"
    path.write_text(json.dumps(report, indent=2) + "\n")
    path.chmod(0o600)
    (root / "request.json").unlink(missing_ok=True)
    print(json.dumps({"ok": report["ok"], "calls": len(client.calls), "status": report["status"], "report": str(path)}))
    return 0 if report["ok"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True)
    parser.add_argument("--command-binary")
    args = parser.parse_args()
    root = Path(args.directory).expanduser().resolve()
    root.mkdir(mode=0o700)
    return run(root, str(Path(args.command_binary).resolve(strict=True)) if args.command_binary else None)


if __name__ == "__main__":
    raise SystemExit(main())
