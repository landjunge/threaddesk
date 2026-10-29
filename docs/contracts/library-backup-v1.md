# ThreadDesk library backup v1

This extends the existing desktop backup paths after PR88 (`80453ff`). It does
not implement Codex 3's separate server cold-backup/sync lifecycle or change the
KiraBridge receiver contract. No additional speech module is needed.

## Scope and format

- Portable ZIP `threaddesk.portable-backup`, version **3**, supports JSON and
  SQLite workspaces, including their persistent library, declared directories
  and inert artifact/planning link metadata. Portable v1/v2 remain readable;
  v1 retains its historical scope without library files. The existing path is
  extended; there is no second backup engine or new service.
- Directory `threaddesk.workspace-backup`, version **3**, includes the library
  with the SQLite workspace snapshot. Versions 1 and 2 remain readable. Creation
  without library data still emits version 2. A current reader is required for
  the newer formats; older readers fail explicitly instead of dropping files.
- Persistent library paths are `library-files/blobs/<64 lowercase hex>`,
  `library-files/records/<12 lowercase hex>.json`, `journal.json`, `index.json`
  and `receive.sqlite3` directly under `library-files`.
- Disposable upload staging directories, hidden blob partials, shared-memory
  sidecars, lock files and unrelated files under the library are excluded.
  These are not acknowledged stored copies. An incomplete receive transfer's
  acknowledged chunks remain inside its database and are included.
- Originals and external thread file references remain at their original
  locations. A backup does not acquire new source-path permissions on restore.

## Capture and consistency

The shared storage module `storage/library_backup.py` captures regular files
through the existing descriptor/handle-relative no-follow source adapter. The
source root, ancestor directories and observed file identities/stamps are bound
through the copy. Symlinks, reparse points, hardlinked persistent library files,
special files and files in place of reserved directories are refused. An
alias with different case for a canonical library path is also refused rather
than omitted from capture. An
interrupted hardlink publication must first be repaired by an explicit receiver
mutation; backup does not unlink or repair anything in the source.

The receiver's main database and any WAL or rollback journal are captured into
private staging together. SQLite opens only that private copy, recovers it if
necessary, checks its integrity and backs up its committed view into a standalone
database. Temporary sidecars are removed only from that owned private staging.
The source database is never reopened by SQLite, checkpointed or recovered by
this operation. SQLite connections belonging to the main workspace keep their
existing backup API behavior. No active receiver process or service is stopped.
The receiver never uses `ATTACH`; rollback trailers naming a super-journal are
refused before SQLite opens the copy, preventing recovery from following that
external journal reference. This follows the
[SQLite pager trailer format](https://sqlite.org/src/doc/trunk/src/pager.c) and
[multi-database journal rules](https://www.sqlite.org/lockingv3.html).

The source library inventory must still match after normalization and semantic
verification. Observed writes/checkpoints/publication changes refuse the backup;
the caller may retry. JSON capture retains the existing workspace writer lock.
SQLite workspace capture also checks the live connection's data version and
change count around the core/library snapshot. This is an optimistic capture,
not a new distributed writer lock or a general transaction spanning every file.
The protected source adapter and normal cooperative writers are required;
arbitrary same-user attacks on a newly created staging parent are outside the
existing backup contract.

## Verification and restore

Each stored record must identify its existing blob with matching SHA-256 and
size. Complete unreferenced blobs are preserved too, supporting interrupted
publication before record creation. A successful import-journal entry must
retain its corresponding verified record. Committed receiver receipts must
identify the stored record and expected hash/size/transfer/thread. Pending
chunks retain their contiguous offsets and bytes; missing/orphaned chunks are
refused. Aborted transfer tombstones and historical receipts survive unchanged.
Reassignment of a record does not rewrite a historical receive receipt.

Archive checksums alone do not replace these library checks. Restore validates
the private copied library before selecting/publishing the new profile. A
recomputed ZIP manifest cannot hide a missing blob, forged receipt, discarded
successful import or foreign SQLite sidecar. Invalid data leaves the current
profile and source files unchanged. This is integrity verification, not backup
author authentication or a malware scan. The existing index is preserved with
its saved status, including any honest partial/failed state; it is derived data
that existing library commands can rebuild from verified copies.

Restore first verifies the exact archived bytes. The existing JSON store may
then reconcile a stale legacy thread revision anchor while validating models;
the archive retains the original payload. A readback must distinguish a proven
revision/content-anchor reconciliation from unexplained changes to business
fields. Caretaker disablement and permission normalization are intentional
restore changes, not omissions from the integrity manifest.

Restoration opens a separate profile. It never replaces the original workspace
or automatically resumes a transfer/import. An explicit receiver call with the
same transfer ID can continue from the restored offset and obtain the existing
durable receipt. An import's saved source path remains metadata; clicking resume
continues to require a valid explicitly selected local source under the existing
import rules. The local caretaker remains disabled after portable restoration.

## Limits and acceptance

File-backed portable archives use one-MiB streaming chunks and ZIP64. Default
limits are **8 GiB** for uncompressed payload plus manifest and for the resulting
ZIP, **200000 entries** including file, directory and inert-link metadata, and
**32 MiB** for the manifest. Export, inspection and restore accept explicit lower
budgets and reject an exceeded limit; they never omit files to fit. The legacy
`download_backup()` bytes wrapper remains bounded to **128 MiB**; the desktop,
command export, artifact download and restore paths use file-backed APIs.

`export_backup(store, target)` verifies the finished archive and publishes without
overwriting a destination. `inspect_backup` and `restore_backup` accept bytes,
a regular path or a seekable stream. Path inputs are descriptor-bound and
no-follow; restored data is validated before a separate profile is activated.
Raw receiver capture fits the remaining capture budget; active WAL/journal
overhead may conservatively require additional space before normalization.
The directory WorkspaceBackup API retains its existing optional library budget.

Portable v3 also includes Tool-Planung, Workflow, Zukunftsvisionen, Bilder,
grok-runtime, handoffs and authority-live-watch. Hidden files inside declared
artifact/planning/runtime data trees are preserved. Runtime root locks, active
profile/port controls and disposable library staging/search projection remain
outside the portable data scope. External thread file references remain external.

Symlinks are accepted only as inert `{target: ...}` metadata within the declared
noncanonical artifact/import/planning trees. Neither export nor restore follows
the target, and restore never creates a symbolic link. Metadata survives reexport
through the new profile's `.profile-info.json`. Canonical store/library links and
root aliases remain refused. Empty declared directories are preserved. Restore
normalizes regular file permissions to 0600 and directories to 0700; this is a
private data restore rather than an executable system image.

Regular data inventories, observed identities and comparison hashes must stay
stable. `library-watch.json` is a declared `point_in_time` file because its poller
updates it during long exports: a descriptor-bound stable read is hashed and
saved, while subsequent status-only rewrites do not invalidate unrelated data.
The manifest explicitly labels that exception. The exported source is not a
transaction spanning independent services. Arbitrary SQLite files in historical
artifacts are preserved as bytes, including deliberately invalid fixtures; only
known canonical databases use their existing private snapshot/validation rules.

Tests use synthetic JSON and SQLite workspaces and preserve original files.
Acceptance covers ordinary restore, persisted receipts, resumed chunks, committed
WAL frames, hot rollback recovery confined to private staging, source changes,
semantic tampering, path/link rejection and legacy format reading.

On 24 October 2026 the user temporarily removed Windows from active development.
The native Windows backup job is parked and Windows is removed from the build
matrix. Linux acceptance and both native macOS builds remain required. Existing
Windows code/downloads remain intact; the unresolved native timeout is not a
Windows acceptance result. Automatic historical three-platform release
publication is paused because its verifier still requires a Windows artifact.
No partial release replaces existing downloads. Other PR/merge gates remain.
