# ThreadDesk library receiver v1

ThreadDesk-side MCP contract, introduced after upstream `64353be`. This is a
local stdio boundary, not a public HTTP upload server. KiraBridge's loaded RC14
catalog on 24 October 2026 has no streaming operation for this contract. Its
adapter and authenticated end-to-end acceptance remain separate work in
KiraBridge. No additional speech module is required: the user talks to ChatGPT/Kira.

## Authorization boundary

The MCP process inherits an owner-authorized ThreadDesk workspace. The upstream
bridge must authenticate the caller and authorize the effective workspace,
existing thread and transfer on **every** call, including status. A transfer ID
is an idempotency key, not a credential. No caller-supplied principal/scope,
source path, URL or destination directory is accepted. Do not offer the write
tool through a read-only dynamic proxy. The three explicitly annotated read
tools are eligible only under the bridge's normal opt-in/authorization rules.
Owner-local storage is trusted against concurrent malicious OS-level replacement;
the receiver rejects pre-existing symlinks, hardlinked control files and special
files, except the verified internal publication pair described below. It is not
an OS filesystem sandbox or a multi-tenant access-control layer.

## Transfer protocol

Call MCP tool `library_receive` with exactly one action's fields. The runtime
validates fields independently of the published JSON Schema.

| Action | Fields besides `action` | Result |
|---|---|---|
| `begin` | `transfer_id`, `filename`, `thread_id`, `size`, `sha256` | Persist the manifest and preallocated record ID; no file is published |
| `append` | `transfer_id`, `offset`, `data_base64` | Append one base64 block at the current byte offset |
| `status` | `transfer_id` | Read offset/state/receipt; never retries work |
| `commit` | `transfer_id` | Verify full size/hash, publish copy, link explicit thread, rebuild index and save receipt |
| `abort` | `transfer_id` | Discard uncommitted blocks, retain the manifest and terminal state |

Example for the UTF-8 bytes `hello`:

```json
{"action":"begin","transfer_id":"kb-file-001","filename":"note.txt","thread_id":"EXISTING_THREAD_ID","size":5,"sha256":"2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"}
{"action":"append","transfer_id":"kb-file-001","offset":0,"data_base64":"aGVsbG8="}
{"action":"commit","transfer_id":"kb-file-001"}
```

Transfer/thread IDs match `[A-Za-z0-9_-]{1,128}`. Filename is one supported
basename (up to 240 UTF-8 bytes); slash, backslash, colon, control characters,
secret-shaped filenames and executable suffixes are rejected. SHA-256 is 64
lowercase hex digits. Size is an integer from zero to 256 MiB. Blocks contain
1–262144 decoded bytes. Offsets count decoded bytes, not base64 characters.
At most 32 receiving transfers reserve at most 512 MiB per workspace. Commit or
abort releases the active reservation. Completed receipts and stored copies are
retained; historical disk usage is not a total-library quota.

On uncertain delivery, call `library_receive_status` with `{"transfer_id":"..."}`.
Missing transfers return `found:false`. Otherwise the response contains
`found:true`, `transfer_id`, `state`, `next_offset`, `manifest`, `receipt` and
`max_chunk_bytes`. States are `receiving`, `committed`, `aborted`.

An identical `begin` returns the existing state; a changed manifest conflicts.
An identical block at its original offset is a safe retry; changed bytes conflict.
Gaps, overlaps and bytes beyond declared size are refused. After restart, resume
from `next_offset`; never invent an offset from a transport acknowledgement.
Commit is repeatable and returns the same durable receipt. Abort is repeatable
but cannot remove a committed file; aborted IDs cannot be reused. Empty files
are committed without appending a block.

Chunks and offsets commit together in a private SQLite WAL database with FULL
synchronous mode. After an interrupted write, read-only status reads the last
committed snapshot without restoring pages into the main database. SQLite may
maintain its shared-memory sidecar; status does not commit or abort a transfer.
Commit flushes published bytes/record before the receipt.
If publication is interrupted, the preallocated record ID allows a commit retry
to repair its thread link without creating another record. A failed commit
keeps blocks available; it may already have published a verified copy and record.
If a process exits immediately after exclusive hardlink publication, read-only
status validates the internal temporary-name/blob pair without changing it.
The next explicit write removes only the temporary name after verifying both
regular-file identities, an exact link count of two and the digest. Unknown,
external or mismatched hardlinks are still refused without deleting anything.
Read status and retry the same ID. Do not start a replacement transfer blindly.
Concurrent legacy local imports retain their existing owner-local behavior;
there is no general transaction spanning all library files and thread storage.

Receipts have format `threaddesk.library.receipt.v1` and contain transfer ID,
record ID, byte SHA-256, size, explicit thread ID, a relative `open_path` and index
status. `committed` proves receipt/publication at that time, not authenticity of
the original source, absence of malicious content, future integrity, complete
semantic indexing or successful opening in an external desktop application.
Supported text files retain the existing bounded secret-pattern check; this is
not comprehensive DLP. ZIP uploads remain opaque files: this protocol does not
extract archives. Source originals are never opened or modified by the receiver.

Stable receiver error codes include `validation_error`, `transfer_missing`,
`transfer_conflict`, `transfer_closed`, `offset_conflict`, `chunk_conflict`,
`invalid_base64`, `chunk_size`, `size_mismatch`, `transfer_incomplete`,
`checksum_mismatch`, `receive_quota`, `unsafe_store`. Existing import errors
(for example `secret_content`, `integrity`) also refuse publication/success.
Unexpected storage failures are MCP errors; a failed response never constitutes
a successful receipt. Repair the reported condition and inspect the same ID.

## Search and opening

`library_search` takes required `thread_id`, `query` (1–1000 characters) and
optional `limit` (1–100, default 20). It reads the saved index without modifying
it or reading original files. Results contain index status, hits, and the limit.
The limit bounds results; it is not an exhaustive/paginated listing. Metadata and
at most the first 32 KiB of supported text files are indexed. PDF/Office/media
content extraction is not implemented. An absent/failed index is reported, not
silently presented as a complete search.

`library_file_info` takes exactly `thread_id`, `record_id`. It verifies the
selected stored copy's hash and size and returns metadata plus
`/library/files/<record_id>`, relative to the actual local ThreadDesk UI origin.
The existing protected UI serves this route as an attachment. This tool does
not launch a program, fetch an external URL or bypass browser/localhost access
controls. Check its explicit thread binding before offering the download.
Missing records are refused; damaged records/blobs, path escapes and symlinks
fail closed. Search text and filenames remain untrusted user data.

Current library-aware backups include `library-files`, stored copies, receive
receipts and pending chunks through a self-contained database snapshot.
[Backup formats, limits and concurrent capture rules](library-backup-v1.md)
define this extension. Historical portable v1 and workspace v1/v2 backups omit
the library; their existence is not proof that received files were backed up.

KiraBridge integration must discover and explicitly authorize these tools,
stream bounded blocks, retain transfer IDs/offsets, read back the final receipt
and verify expected hash/size/thread before reporting success. A transport task
receipt or successful tools/list call alone is insufficient. No productive
bridge configuration or existing queued task is changed by this implementation.
