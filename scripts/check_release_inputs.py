"""Reject accidental runtime data in Git. This is not a complete secret audit.

Inspect committed blobs, never the user's home directory or symlink targets.
Synthetic tests deliberately contain invalid credentials used in negative tests.
"""
from __future__ import annotations

from pathlib import PurePosixPath
import re
import subprocess

RUNTIME_NAMES = {
    "rooms.json", "peers.json", "invites.json", "actors.json", "hausmeister.json",
    "desktop-port.json", "desktop.lock", "threaddesk.sqlite3",
}
RUNTIME_ROOTS = {".threaddesk", ".threaddesk-local", "data", "backups", "user-data", "test-results", "playwright-report"}
SECRET = re.compile(rb"(?:ghp_|github_pat_|sk-proj-)[A-Za-z0-9_\-]{24,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")


def inspect(name: str, mode: str, body: bytes) -> list[str]:
    path = PurePosixPath(name)
    reasons = []
    if mode == "120000":
        reasons.append("symbolic link")
    if path.parts[0] in RUNTIME_ROOTS or path.name.lower() in RUNTIME_NAMES:
        reasons.append("runtime workspace data")
    if path.suffix.lower() in {".db", ".sqlite", ".sqlite3", ".tdbundle", ".p12", ".pfx"}:
        reasons.append("database, import bundle or credential container")
    if path.name == ".env" or path.name.endswith(".env"):
        reasons.append("environment configuration")
    if not name.startswith("tests/") and SECRET.search(body):
        reasons.append("secret-shaped value outside synthetic tests")
    return reasons


def main() -> None:
    records = subprocess.check_output(["git", "ls-tree", "-r", "-z", "HEAD"]).split(b"\0")
    checked, rejected = 0, []
    for record in records:
        if not record:
            continue
        header, raw_name = record.split(b"\t", 1)
        mode, kind, object_id = header.decode("ascii").split()
        name = raw_name.decode("utf-8")
        if kind != "blob":
            rejected.append((name, ["unreviewed nested repository"]))
            continue
        body = subprocess.check_output(["git", "cat-file", "blob", object_id])
        reasons = inspect(name, mode, body)
        checked += 1
        if reasons:
            rejected.append((name, reasons))
    if rejected:
        for name, reasons in rejected:
            print(name + ": " + ", ".join(reasons))
        raise SystemExit("Release inputs rejected; no file contents were printed")
    print(f"Release inputs: {checked} committed files checked; no prohibited runtime files found")


if __name__ == "__main__":
    main()
