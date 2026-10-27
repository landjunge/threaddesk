"""Verify explicit Keynote originals through fresh public command processes.

Only metadata and hashes enter the report. Input originals remain unchanged;
external Keynote application launch is deliberately not inferred from import.
The caller must supply the actual bridge principal/task evidence separately.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path

from check_workspace_commands import Client


def sha(body):
    return hashlib.sha256(body).hexdigest()


def run(root, originals, binary=None):
    client = Client(root, binary)
    thread = client.call("thread_manage", {"action": "create", "data": {"title": "Format acceptance"}},
                         operation="format-thread", revision=0)["thread"]["id"]
    source = root / "owned-originals"
    source.mkdir()
    expected = {}
    for index, original in enumerate(originals):
        body = original.read_bytes()
        name = "Presentation-" + str(index) + ".key"
        (source / name).write_bytes(body)
        expected[name] = {"sha256": sha(body), "size": len(body)}
    imported = client.call("library_manage", {"action": "import", "data": {"source": str(source), "thread_id": thread}},
                           operation="format-import")
    assert imported["complete"] and len(imported["files"]) == len(originals)
    rows = []
    for item in imported["files"]:
        record = client.call("library_query", {"action": "info", "id": item["record_id"]})
        wanted = expected[record["filename"]]
        assert record["sha256"] == wanted["sha256"] and record["size"] == wanted["size"]
        preview = client.call("library_query", {"action": "preview", "id": record["id"]})
        assert preview["kind"] == "metadata" and preview["can_open"]
        assert not preview["formats"]["index"] and not preview["formats"]["preview"]
        assert preview["record"]["content_validation"]["sha256"] == wanted["sha256"]
        rows.append({"id": record["id"], **wanted, "preview": "metadata", "content_identity_validated": True})
    # The receive protocol validates the same exact bytes before publication.
    body = originals[-1].read_bytes()
    transfer = "keynote-receive"
    client.call("library_receive", {"action": "begin", "transfer_id": transfer, "filename": "Received-Presentation.key",
                "thread_id": thread, "size": len(body), "sha256": sha(body)}, operation="receive-begin")
    for offset in range(0, len(body), 12000):
        client.call("library_receive", {"action": "append", "transfer_id": transfer, "offset": offset,
                    "data_base64": base64.b64encode(body[offset:offset + 12000]).decode()}, operation="receive-part-" + str(offset))
    receipt = client.call("library_receive", {"action": "commit", "transfer_id": transfer}, operation="receive-commit")
    assert receipt["state"] == "committed"
    status = client.call("library_receive_status", {"transfer_id": transfer})
    assert status["state"] == "committed"
    invalid_source = root / "invalid-originals"
    invalid_source.mkdir()
    (invalid_source / "Unknown.key").write_bytes(b"not a Keynote document")
    (invalid_source / "credentials.key").write_bytes(b"synthetic excluded filename fixture")
    directory = invalid_source / "Package.key"
    directory.mkdir()
    (directory / "nested.txt").write_text("must not be imported as a presentation")
    rejected = client.call("library_manage", {"action": "import", "data": {"source": str(invalid_source), "thread_id": thread}},
                           operation="format-rejected")
    assert not rejected["complete"] and all(item.get("status") != "stored" for item in rejected["files"])
    for index, original in enumerate(originals):
        assert sha(original.read_bytes()) == expected["Presentation-" + str(index) + ".key"]["sha256"]
    report = {"ok": True, "fixture_only": True, "command_binary": binary, "records": rows,
              "originals_preserved": True, "receiver_state": status["state"], "invalid_formats_rejected": True,
              "external_keynote_launch": "not requested; no application launch claim",
              "calls": [{"command": call["command"], "operation_id": call["request"].get("operation_id"),
                         "exit_code": call["exit_code"], "request_sha256": sha(json.dumps(call["request"], sort_keys=True).encode()),
                         "response_sha256": sha(json.dumps(call["response"], sort_keys=True).encode())} for call in client.calls]}
    path = root / "format-admission-result.json"
    path.write_text(json.dumps(report, indent=2))
    path.chmod(0o600)
    (root / "request.json").unlink(missing_ok=True)
    print(json.dumps({"ok": True, "calls": len(client.calls), "originals_preserved": True, "report": str(path)}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True)
    parser.add_argument("--keynote-file", action="append", required=True)
    parser.add_argument("--command-binary")
    args = parser.parse_args()
    root = Path(args.directory).resolve()
    root.mkdir(mode=0o700)
    run(root, [Path(path).resolve(strict=True) for path in args.keynote_file], args.command_binary)


if __name__ == "__main__":
    main()
