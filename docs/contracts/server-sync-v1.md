# ThreadDesk Server & Sync v1 — implementation contract

Basis: project c2d4c7bc985a revision 3, coordination 188ce4729a62 revision 11,
Codex 2 source 0aa268a. This additive module does not change MCP library-receive-v1.
Server entry point is separate from the localhost desktop HTTP boundary. Shared
ThreadDesk ThreadService/JsonStore supplies project threads and whiteboards.

## Ownership and transport

Each authenticated user has a server-selected private directory and SyncStore.
No request accepts a tenant directory. All project/transfer/revision operations
are scoped by that store. TLS is mandatory except explicit loopback development.
Browser login exchanges an operator-created random access token for a session;
machine clients use Bearer tokens. Tokens are stored hashed in private config.
No remote shell, filesystem path open, execution or KiraBridge changes.

## Core Python boundary (SyncStore in threaddesk.server_sync.store)

Constructor SyncStore(root: Path). Each method uses a durable SQLite transaction.
Errors: SyncError(message, code='invalid', status=400); .code/.status are public.

- create_project(title, project_id=None) -> project dict; projects(); project(id).
  Project dict: id,title,offline_enabled. IDs safe ASCII, random by default.
- set_offline(project_id, enabled) -> project. False prohibits NEW byte uploads;
  never deletes previously stored copies, versions or local originals.
- declare_manifest(project_id, files, issues, device_id) -> status. Files are
  [{path,sha256,size}]; issues list[str]. Metadata only, even when disabled.
- status(project_id) -> {state,offline_enabled,missing_files,required_bytes,
  conflict_count,issues,...}. States metadata_only,pending,blocked,conflict,ready.
  Ready requires at least one complete declared manifest, no issues/conflicts,
  and current verified content for each declared path. Changes invalidate ready.
- list_files(project_id) -> [{path,heads:[{revision,sha256,size}]}].
- start_upload(project_id, transfer_id, path, size, sha256, base_revision=None)
  -> upload_status dict. append_chunk(project_id,transfer_id,offset,data:bytes)
  -> status; upload_status(project_id,transfer_id) -> {next_offset,state,receipt}.
  finish_upload(project_id,transfer_id) -> receipt dict including revision.
  Persistent blocks, exact retries, <=256KiB/block, <=64MiB/file, <=1GiB/tenant;
  bound active transfer reservations. Commit verifies size and SHA256 and retains
  immutable versions. A stale base creates another head, never replaces a head.
  A repeated commit returns its original receipt, including after restart.
- read_revision(project_id,revision) -> bytes, verified against recorded hash.
- history(project_id,path) -> all retained revision/hash/size/is_head records.
- pending_uploads(project_id) -> unpublished receiving transfers and offsets.
- abort_upload(project_id,transfer_id) -> status; frees only unpublished blocks
  and reservations. Committed versions/receipts remain unchanged. An absent ID
  becomes an aborted tombstone, preventing delayed begin from allocating space.
- resolve(project_id,path,expected_heads:list[str],chosen_revision) -> file dict.
  CAS on exact heads, chosen existing head retained, all old versions retained.

Paths are logical POSIX relative paths, never executable filesystem destinations.
Reject absolute paths, traversal, backslashes, controls, empty/dot segments and
secret-bearing paths (.env, credentials, private keys, VCS internals). File data
is inert storage; do not use library's extension denylist for project source.

## HTTP boundary (threaddesk.server_sync.app)

All /api calls authenticated; loopback-only developer mode must be explicit.
GET/POST /api/projects; GET /api/projects/{id}/status;
PUT /api/projects/{id}/offline {enabled:bool};
POST /api/projects/{id}/manifest {files,issues,device_id};
GET /api/projects/{id}/files;
GET /api/projects/{id}/history?path=relative/path;
GET /api/projects/{id}/uploads;
POST /api/projects/{id}/uploads/{transfer} {path,size,sha256,base_revision};
GET /api/projects/{id}/uploads/{transfer};
PATCH same {offset,data_base64}; POST same /commit;
POST same /abort;
GET /api/projects/{id}/revisions/{revision} (attachment bytes);
POST /api/projects/{id}/resolve {path,expected_heads,chosen_revision}.
Metadata core: GET/PUT /api/projects/{id}/thread (description,notes),
GET/POST /api/projects/{id}/whiteboard (content,entry_type).

## Local client (threaddesk.server_sync.client)

One explicitly selected project directory, recursively enumerated on each sync;
new files included. No symlink traversal or deletion. Discover relative references
within the selected tree; external/missing/unsafe dependencies block readiness
and require explicit operator mapping, never silently scrape the host.
Keep a private SQLite checkpoint per client root/project/server identity.
Use last common revision as upload base, download server changes by hash and
atomically install only when local bytes still equal the checkpoint. Concurrent
changes keep local bytes AND an extra conflict copy, and upload both histories.
Restart resumes same transfer ID and server offset; uncertain responses never
invent success. Reconnect loop retries boundedly and updates visible status.
Remote removals are metadata only; no automatic local/server deletion or GC.
Displaced local inodes and remote conflict copies have private JSON sidecars
mapping each generated recovery copy to its original path and known revision.
Known VCS internals are omitted; explicit references to them block readiness.
The standalone file CLI synchronizes file content. DesktopSyncManager binds an
explicit existing local ThreadService/workspace/thread, captures its local file
grants in a private owner-authorized list separate from replicated context, and
passes MetadataReplica to SyncClient. Automatic runs never rebuild grants from
merged context.files. Explicit protected local add/remove actions amend authority;
old bindings without separate provenance default to no extra grants. Ordinary
filesystem references are literal; only explicit file: URIs decode escapes.
Additional local context references remain required validation data: unapproved
new attachments block readiness rather than silently disappear from inventory.
They are never passed as source grants. Exact already-inventoried physical names
can satisfy validation without reinterpreting URI escapes.
File checkpoint directories include the selected root; metadata checkpoints keep
their existing workspace/thread/server scope when the project directory moves.
For the same Desktop server/project binding, the persisted manifest reporter
`device_id` survives root changes. Legacy bindings recover that identity only
from a private checkpoint whose URL/project/saved-root/credential identity
matches exactly; an ambiguous or invalid checkpoint is refused, not rebound.
The new root therefore updates the same reporter instead of leaving another
stale manifest solely because the directory changed.

`SyncClient(..., device_id=None, initial_bases=None)` accepts explicitly validated
binding identity and committed common-base records `{path,revision,sha256}`.
Root relocation reads those base records from the validated old checkpoint in
SQLite read-only mode. Only a pristine new root-bound checkpoint may seed them;
existing checkpoints and pending operations are never reset. Pending uploads,
source mappings and source grants are NEVER migrated. Original checkpoints stay
untouched, and current explicit local grants still determine every destination.
A migrated base preserves ancestry, not permission to overwrite: unknown bases,
stale bases and concurrent remote changes retain the normal conflict protection.
SourceFile mappings returned by discover_project determine descriptor-bound reads
AND original write destinations. Revoked grants, unknown external namespaces and
exact-file siblings cannot become write targets. Recovery stays on the target's
filesystem. Static Python/JS/TS/HTML/CSS/Markdown/manifests are inspected without
executing code; unresolved dynamic dependencies prevent readiness.

## Desktop and metadata additions

Desktop has one protected POST /threads/{id}/server-sync action boundary,
read-only configuration/status views, private 0700/0600 bindings and automatic
reconnect while the application runs. Policy-generation CAS prevents an old
in-flight result from undoing a newer offline toggle. Tokens never enter
replicated core metadata or views; changed server origins require new credentials.

POST /api/projects/bind {binding_id,title} creates a deterministic scoped project
with durable bootstrap receipt. Replays return that receipt. A pre-existing
thread without its binding receipt is not silently adopted as pristine.
MetadataReplica.seed_base only seeds an unused checkpoint, never pending work.

- GET /api/projects/{id}/metadata -> {document}.
- POST .../metadata/sync {operation_id,base,document} -> merged document/conflicts.
- GET .../metadata/conflicts -> unresolved historical conflicts.
- POST .../metadata/resolve {conflict_id,expected_current,chosen_value,operation_id}.

Document format threaddesk.metadata.v1 includes thread fields, portable project/
task nodes and relations, and append-only whiteboards. Portable project origins
map to existing/local IDs, including organization.project_id and owned tasks.
Absolute file references remain local; incoming safe relative refs are inert and
never grant access outside an existing source grant. Agent state is not exported.
Three-way field merges, atomic core receipts and previous snapshots protect
concurrent values and uncertain responses. Replication never dispatches tasks.
Deterministic imported node/relation IDs are checked against current scope before
creation; an object moved to another project cannot be overwritten on reconnect.
The whole transaction returns metadata_scope409 without partial publication.
Opaque namespace identity is journaled durably, surviving path changes and full
backup/restore. Documents are bounded to 1 MiB each, metadata HTTP bodies 4 MiB;
other request bodies retain the 512 KiB transfer bound. No silent truncation.
Manifest requests have a separate 96 MiB UTF-8/JSON bound for the declared
20000-file inventory (2048-byte paths, escaping and bounded issues); both header
and streamed-body checks use the same endpoint limit. Upload blocks keep the
original 512 KiB HTTP / 256 KiB decoded-byte limits.
The production Caddy template applies matching request limits before proxying:
POST project manifests 96 MiB, POST metadata subroutes 4 MiB, all other requests
512 KiB. Metadata/manifest capacity does not increase ordinary upload limits.
When local metadata equals the last common base and no uncertain operation is
pending, authenticated conditional GET/ETag proves an unchanged server without
writing another receipt, snapshot or checkpoint. Pending operations still replay
their original durable request. Idle automatic polling therefore does not grow
the immutable metadata journal with repeated copies of the same document.
A positively confirmed server-aborted file upload gets a newly persisted
replacement transfer ID, with at most two begins per sync run. Uncertain replies
retain the current checkpoint; committed receipts and old versions stay intact.
The browser follows the same bounded rule per upload action: only an explicit
`aborted` state permits replacement, and the replacement ID is written to
`sessionStorage` before another begin. A second confirmed abort stops the action;
timeouts and unknown replies never imply cancellation or success.

## Complete server backup

backup(data_dir,output) and restore(archive,new_data_dir) use format
threaddesk.server.backup.v1. Server ASGI lifespan and account initialization hold
the same exclusive lifecycle lock; API without startup is refused. Cold backups
include every regular file/empty directory except that transient lifecycle lock,
including credentials, core, snapshots, immutable versions, pending chunks,
conflicts and receipts. Output/restore targets are NEW, never overwritten.
SHA256 manifests, SQLite quick_check, version hashes and chunk offsets are checked
before atomic restore publication. Reject symlinks/hardlinks, traversal, duplicate
archive paths, unsupported tar extensions and insufficient space. Bounds are
4 GiB content, 100000 entries and 16 MiB manifest. Arbitrary external filesystem
writers outside the lifecycle contract remain an operator trust boundary.

## Delivery gates

Targeted checks during development; repository-required complete CI applies before
the authorized PR/merge. Codex 2 PR88 is incorporated through committed main.
Actual isolated Linux/amd64 build, verified private-CA TLS, restart, complete
restore and Desktop/browser integration evidence is in the follow-up report.
No public deployment or release is implied. KiraBridge's independent contract
remains unchanged. Arbitrary runtime dependency completeness cannot be proved;
reported unresolved dependencies fail closed rather than claim readiness.
