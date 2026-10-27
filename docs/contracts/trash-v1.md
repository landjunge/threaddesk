# Reversible object lifecycle v1

`services.trash.TrashService` owns thread, knowledge-node and relation lifecycle.
Library file records keep their existing independent lifecycle; no generic
operation deletes an external original or shared CAS blob.

The service has the same public methods for every transport:

| Method | Arguments | Result |
| --- | --- | --- |
| `list` | `state=trashed`, optional `kind`, `offset=0`, `limit=50` (max 100) | `items`, `total`, `offset`, `next_offset`, `version` |
| `get` | exact `trash_id` | Lifecycle entry |
| `preview` | `kind`, `object_id` | Original object, preserved references, reference digest and purge blockers |
| `move` | `kind`, `object_id`, `expected_revision`, `operation_id`, optional caller label `actor` | Entry, operation ID, duplicate flag |
| `restore` | `trash_id`, `generation`, lifecycle `expected_revision`, `operation_id` | Entry and unresolved references |
| `purge_preview` | `trash_id` | Fresh reference digest, blockers and exact confirmation text |
| `purge` | `trash_id`, `generation`, lifecycle `expected_revision`, `reference_digest`, exact `confirmation`, `operation_id` | Minimal retained tombstone |
| `operation_status` | Public `operation_id` | `found` and independently readable stored result |
| `sync_conflicts` | none | Durable lifecycle conflicts and current object digests |
| `resolve_sync_conflict` | `conflict_id`, `expected_object_digest`, `choice=keep_local` or `adopt_incoming`, `operation_id` | Explicit resolution and preserved local payload |

IDs accept ASCII letters, digits, underscores and hyphens. A move accepts legacy
object revision zero; lifecycle revision and generation start at one. A caller's
actor label is explicitly marked `caller_label`, not authenticated identity.
The actual authenticated principal remains transport execution evidence.

Payloads, snapshots, whiteboards, provenance and relations remain in their
original stores. Normal lists and direct mutations exclude or reject trashed
objects with `object_in_trash`; internal lifecycle/migration/sync readers use an
explicit `include_trashed=True`. Trashing a thread hides its linked graph nodes
and incident edges without cascading deletion. Restore preserves IDs and never
selects a thread automatically. Missing parents/endpoints are returned as
unresolved references rather than silently reassigned.

`trash_id` binds the exact object and generation. Restore followed by another
move creates a new generation; a stale restore cannot affect it. Every mutation
binds its operation ID to a canonical request hash in the same transaction as
its result. Same request is replayed; different content gives
`operation_conflict`. Lifecycle revision, object revision and generation
conflicts are distinct. A changed payload from an older or rogue writer yields
`object_changed_in_trash` instead of silent restore or purge.

JSON uses the existing management lock and durable commit journal. SQLite
schema migration 7 adds `trash_entries`. Portable backup, SQLite backup and
JSON-to-SQLite migration retain hidden objects, history, generations and
operation records. Migration also transfers activity and saved-view owner
documents atomically into SQLite's explicit migrated-owner-document source;
the owning service uses that source only until a newer owner file exists.

Purge is never automatic. Its exact text is
`DELETE <trash_id> <reference_digest>`. Current reference digest, generation,
lifecycle revision and unchanged object content are checked again inside the
transaction. Existing graph, library, organization, provenance or issued
handoff references block purge for explicit review. External files and library
blobs remain intact. Historical low-level permanent deletion is a legacy
contract and must not be presented as the new trash action.

Purge preview version 2 also binds the exact active operation-result copies
and every historical trash generation. `receipt_reduction.records` lists
storage IDs, old record/result hashes, the reduced-result hash and affected
JSON paths; it never includes the old result body. These records and the
trash-history reduction become part of `reference_digest` and therefore of
the exact `DELETE` confirmation. A changed or additional affected receipt
invalidates the preview. Requests made against an older preview must refresh
it before any destructive action.

Inside the same JSON journal/SQLite transaction, recognized copies of the
selected thread, snapshots, whiteboard entries, node or relation become
`threaddesk.purged-payload.v1` evidence. A legacy administration result keeps
`thread: null` and explicit `purged_payloads`; its action, object/operation
IDs, revision and duplicate semantics remain readable. The original
`request_hash`, execution state, timestamps and storage identity remain
unchanged. The explicit exception to append-only result storage adds
`threaddesk.purge-receipt-reduction.v1` evidence containing old/new hashes,
payload paths and the authorizing purge identity. Identical owner/global
replays return reduced content without re-execution; changed requests still
conflict. Old move/restore result copies and all trash generations also lose
their titles, actor labels and reference/path lists. Unrelated owned results
are retained.

Unknown target-bound fields and unattributed text results, including the
legacy `generate_prompt` result `{text: ...}` and nested copies of that
shape, are explicit purge blockers. No content-based guess silently edits
another prompt or audit record. Unconfirmed global commands block purge,
because their in-flight handlers could otherwise publish an old result after
purge. Only this purge's own pending command may be exempted, after checking
the complete canonical command/workspace/arguments/operation/revision hash;
an operation-ID match alone is insufficient. Inventory limits (20,000
receipts, 32 MiB of inspected receipt data, depth 40 and 100,000 traversed
values per result) fail closed for review.

New backups and restored public operation views contain reduced active
records. This contract does not promise secure byte erasure: physical SQLite
snapshots can retain historical content in free database pages, and old
external backups, exported prompts, external originals and shared data remain
outside this purge. No production VACUUM or filesystem secure-wipe runs. A
private-copy compaction experiment is verification evidence only; it is not
part of the backup implementation or a guarantee of forensic erasure.

Room bundles add `threaddesk.room.v2` only when lifecycle history exists.
Authenticated peers exchange generation/state and a content digest; differing
private or shared edits become durable conflicts. Old bundles cannot resurrect
a trashed thread or overwrite a restored generation. Metadata replicas use
`threaddesk.metadata.v2` with scoped lifecycle fields for threads, project/task
nodes and relations. Delete/edit races, stale generations, legacy writers and
remote purge requests are retained as conflicts. Lifecycle conflict resolution
binds the whole current object/document digest and never restores an older
generation. Adopting one previously refused restored generation requires an
explicit choice; automatic synchronization cannot infer it. A remote purge grants no local
destructive permission. V1 peers reject v2 explicitly; absence never means
deletion. Existing pre-lifecycle v1 exchange remains compatible.

All configured writers must use a compatible source pin before activation.
Neither JSON locks nor schema fields can prevent an unrelated older executable
from writing raw files; release verification must inspect the actual writers.
KiraBridge is unchanged. Native bridge write-contract limits and the authorized
visible CLI path are documented by the transport integration evidence, not
inferred from these service methods.
