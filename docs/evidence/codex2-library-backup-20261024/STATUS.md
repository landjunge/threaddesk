# Codex 2 / ThreadDesk — library backup, 24 October 2026

Base: merged PR88, `80453ff993892ea7297261a34f9698c0bc5c813d`.
Branch: `feat/codex2-library-backup-20261024`.
The existing clean Codex 2 worktree was reused; the source-pinned older Tauri
candidate and its ignored build files remain available. The dirty main checkout,
KiraBridge and Codex 3's server/sync worktree were not changed. Coordination uses
the existing shared thread `188ce4729a62`, with entries labelled Codex 2.

## Confirmed problem and scope

Three new roundtrip cases first failed on the merged baseline: portable JSON,
portable SQLite and directory WorkspaceBackup all restored the core threads but
returned zero library records. This was the library omission recorded in PR88.

The new shared `storage/library_backup.py` captures persistent library files,
import journal, index, receive receipts and pending chunks. It borrows the
already-bound core source tree when invoked by existing backup paths, refusing
source rebinding or changes. Only the private descriptor-captured receiver copy
is opened by SQLite; WAL/rollback recovery and normalization happen there.
The source receiver DB and sidecars are not checkpointed or modified.

Portable v2 and workspace v3 formats include the library; legacy formats remain
readable with their previous scope. Workspace creation without library data
still produces v2. Restore checks record/blob hashes and sizes, successful
import references, committed receipts and contiguous pending chunks before
publishing/selecting a separate profile. Metadata and artifact observations
remain stable through capture; concurrent core SQLite edits refuse publication.
Canonical library case aliases, links, wrong directory types and foreign
SQLite sidecars fail explicitly. No original files or selected profile are
replaced by a failed operation.

Portable limits remain 128 MiB/20000 entries, now also checked against manifest
overhead and final ZIP bytes so a download cannot exceed its own restore limits.
Larger stores are refused in full rather than silently omitting files. The raw
receiver capture budget conservatively includes WAL/journal overhead.

## Verification

The 30 final library cases cover JSON/SQLite copy+receipt+resume roundtrips,
direct WorkspaceBackup, committed WAL frames after subprocess exit, hot
rollback recovery confined to private staging, unchanged source DB/journal
hashes, original-file preservation, root exchange, concurrent core/library
writes, case aliases, symlinks/hardlinks, corrupted receiver DB, recomputed ZIP
hashes hiding semantic corruption, source limits, manifest overhead and legacy
portable format reading. The affected suite passed 207 checks without failures
or skips. After the final super-journal guard, all 30 library checks passed.
These are overlapping sets, not additive; `checks.json` records the results
and source hashes for both checkpoints. Earlier runs of 197 and 123 checks
also overlap. Rollback trailers naming another database's super-journal are
refused before SQLite opens the private copy; the external file remains intact.

Reproduction:

```sh
PYTHONPATH=src /Users/landjunge/threaddesk/.venv/bin/python -m pytest -q \
 tests/test_library_backup.py tests/test_portable_backup.py \
 tests/test_workspace_backup.py tests/test_library_receive.py \
 tests/test_storage_contract.py tests/test_json_control_paths.py \
 tests/test_relative_json_workspace.py
```

The native Windows backup CI job now includes the new library file. Existing
whole-suite/browser/no-skips checks and all release gates remain unchanged.
Local macOS tests are not Windows evidence; final CI results must be recorded
against the actual pushed head. No unnecessary local whole-suite run or new
desktop build was used for this storage-only change.

## Boundaries and coordination

Codex 3's server cold backup remains its separate module under `server_sync`;
this change does not edit its API, client, metadata sync, desktop UI or package
configuration. No live bridge configuration, queued task, clipboard, terminal
or other session was changed. No subagent was started.

The archive preserves the existing index/status rather than claiming full
document-content extraction. Import source paths remain metadata, not a new
authorization to scan another host after restore. Snapshot integrity is not
backup-author authentication or malware detection. Backups contain private
contents and must be stored appropriately; encryption is not added here.

Graphical desktop acceptance, KiraBridge adapter/live end-to-end acceptance and
release-version alignment remain separate open tasks. The existing glib
Dependabot alert in the unchanged Rust lockfile is not resolved by this Python
backup change. Final push/PR/merge status belongs in the shared whiteboard;
the preceding source-pinned desktop artifact is not relabelled as a new build.
