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
The CLI synchronizes file content, not existing desktop metadata/whiteboards.
Server browser metadata uses the shared core with revision CAS and snapshots;
an existing desktop workspace adapter remains a separate integration boundary.

## Delivery gates

Targeted data-loss/restart/authorization/integrity checks only. No merge or
publication. Completeness of arbitrary out-of-tree dependencies cannot be
guaranteed: report the selected root and unresolved references explicitly.
Docker/systemd examples use TLS reverse proxy and private persistent volume;
native Linux installation and live Desktop/KiraBridge integration require actual
acceptance evidence and must not be represented as already verified.
