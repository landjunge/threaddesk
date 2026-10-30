# Graph reads, file activity and saved views

The shared ThreadDesk command application exposes `graph.query`, `activity.files`, `activity.reconcile`, `graph_view.list/get/manage/operation`. Existing `ThreadService.graph()` and `/api/graph` retain `threaddesk.graph.v1`. The new HTTP `/api/graph/v2` is a thin adapter to `graph.query`; it does not implement another query service.

## Evidence and time

`file-activity.json` is a bounded independent owner document. Both JSON and SQLite profiles use the same service. SQLite migration can retain an initial copy in `app_state`; that migration source is read only if no newer owner file exists. Ordinary graph/activity reads create no state or lock files.

The two independent channels are:

- `modified`: a verified source refresh has a different SHA-256 from the confirmed predecessor. `occurred_at` comes from the source timestamp captured with that verified change. Initial imports and duplicate copies create no event.
- `accessed`: the existing explicit open action has a durable `launch_requested` receipt. Its original `launch_requested_at` is the time. `human_read_confirmed` remains false. A requested OS launch does not prove human reading.

Graph opening, query, hover, background preview, index, sync, metadata edits, rename/move, backup and trash/restore do not generate file activity. Record IDs, digests, predecessor and origin kind explain the event; callers cannot submit a fabricated actor or a public arbitrary activity event.

`activity.reconcile` is a declared write, separate from reads. It retries only committed launch receipts and committed source `activity_evidence`, with `limit` 1–100 and `offset`. It never launches a program, reads original bytes or obtains a new source timestamp. The result reports processed/recorded/duplicate/failed counts, bounded errors and `next_offset`. The runtime follows the cursor and starts another pass after its end. Evidence failures do not roll back a completed file operation.

Each write uses a stable prefixed event ID and request digest. Identical replays preserve the activity revision; a different payload under that ID conflicts. Latest per-file channels and the deduplication ledger publish together through private, fsynced atomic replacement under a stable writer lock. A document is limited to 16 MiB and 20,000 event receipts; saturation is reported, never silently pruned.

UTC timestamps require an explicit offset. The fixed elapsed-age bands are ≤86,400 seconds, >1–7 days, >7–30 days, >30–90 days, older, and unknown. Rolling 24 hours are not labelled “today”. Future evidence remains visible with a clock warning and the unknown band. A plain historical `updated_at` is never backfilled as work.

## Graph v2

The v2 response retains nodes, relations and counts and adds `as_of`, `activity_revision`, `activity_status/error`, filter state, `total/returned/next_offset` and a relation-truncation indicator. Corrupt independent activity evidence leaves the graph navigable, explicitly `unavailable`, with unknown channels; the damaged evidence is preserved.

`graph.change_status` and `GET /api/graph/change-status` expose the same inert invalidation probe: `schema=threaddesk.graph.change-status.v1`, the canonical `workspace_id`, `status`, an opaque SHA-256 `fingerprint`, UTC `as_of` and UTC `minute`. An unreadable or concurrently changing snapshot returns `unavailable`, a null fingerprint and a sanitized error code. The fingerprint is a technical change marker, never file activity or a content checksum. No content or filesystem paths are returned.

For JSON, a fixed number of directory and owner-file metadata reads observes the supported atomic canonical publishers, including thread/node/relation/trash commits, library record replacements, file overlays and file activity. It does not enumerate or parse every document. Root-directory timestamps, view-control state, saved views, command receipts, index files and importer/watch journals do not invalidate the graph. SQLite reuses canonical thread/node/lifecycle revision signatures in one read-only snapshot and includes narrow ordered relation revisions plus migrated initial activity. A SQLite progress deadline and a one-second lock timeout bound an unavailable probe; it does not wait on writers indefinitely.

The separate graph-live controller polls visible documents every 7.5 seconds and reuses the existing graph refresh and graph readmodel. Canonical changes or a new server minute refresh nodes, attachments and rolling time bands while preserving the existing camera, surviving selection and positions. Open previews, active pointer gestures, focused fields and unsaved field input defer the update and display a refresh action without shrinking the drawing stage. A deliberate refresh preserves the existing form inputs. Transport failure remains visible and retryable; the last usable graph stays available. A changed workspace invalidates the old view-control capability immediately. With a draft still open, the new workspace waits for deliberate reload; otherwise a fresh document loads and registers its own capability.

Filters: `query`, existing node `kind/status`, `project_id`, `mode`, `band`, `center/hops`, `as_of`, `limit/offset`. Modes are `status`, `modified`, `accessed` and `work`; `work` uses the newest known event from either channel. A neighborhood has at most two hops. Pages contain at most 1,000 nodes and 10,000 internal relations. Clients follow the actual cursor. The UI pages larger graphs and sends filters back to the same service, so a search is not restricted to the first page.

Activity on a non-file node aggregates only actually attached visible file records, confirmed project membership and a nonempty matching thread assignment. Both absent thread IDs do not imply a relationship. Trashed files are excluded. The selected evidence names its file and whether it is attached-file activity. A node without file evidence is unknown.

## Saved views

`GraphViewService.manage` accepts `save` or `delete`, an exact view ID, `operation_id`, `expected_revision`, and data. Creation expects revision zero. A saved state contains:

- `camera`: world coordinates `x/y` at the viewport center and `scale` in screen pixels per world unit, bounded .04–4. This survives inspector/window resizing.
- `positions`: node identity → finite `x/y` and optional Boolean `fixed`, at most 10,000 entries.
- `filters`: graph filters without a historical `as_of` or paging cursor.
- `selection`: at most 100 stable node identities.

The owner document retains revision, generation and atomic operation receipts. Identical replay returns the same receipt; stale revision and changed payload conflict. Save receipts are small summaries; `get` provides the independent full readback. Deleting a view keeps a revision tombstone and does not delete graph/domain data. Limit: 200 saved identities and 10,000 operation receipts within the 16-MiB document budget. Inputs and readback have explicit transport budgets; the frozen command accepts a request file for large states.

The UI preserves an uncertain save request and retries its exact operation instead of creating another view. Controls remain busy through verification. SVG, GPU and the DOM list share selection, filters, inspector and this view contract; selection survives renderer changes.

## Renderer and failure behavior

Small graphs retain the readable SVG path. From 128 nodes, locally bundled Sigma 4.0.3 and Graphology 0.26.0 render the graph. Labels use 14 screen pixels, selected labels 16, with bounded screen-space occupancy. Type shapes, status marks, text and activity intervals remain distinct.

The ForceAtlas2 0.10.1 worker starts only on the explicit arrange action, uses Barnes–Hut, works on a separate graph copy, stops/kills after 1.5 seconds and applies one final position update. Fixed and filtered-out positions stay fixed. This avoids continuous movement, including with Reduced Motion. A generation token cancels delayed starts and duplicate clicks; leaving or losing the renderer kills the worker.

Unavailable WebGL2, initialization failure or context loss opens the paged keyboard/DOM list with the shared inspector. It does not attempt an expensive huge SVG fallback. Worker failure preserves existing positions. All runtime assets are local; exact files, SHA-256 values, build lock and MIT texts are in `graph-vendor.json` and `GRAPH-VENDOR-LICENSES.txt`. `scripts/vendor_graph.py` is an explicit maintenance build, never a startup network operation.

## Explicit delivery to a connected graph

Saving a view alone does not move an already open graph. `graph_view.apply` creates a revision-bound intent; `graph_view.apply_status` reports the separate delivery state. `graph_view.clients` lists leases without exposing capability secrets. One active graph is selected automatically; multiple active graphs require an exact client ID. With no graph attached, the intent reports `waiting`. `queued` and `waiting` are never presented as `applied`.

The graph document registers through the existing protected HTTP session and receives an ephemeral client capability. Registration, heartbeat, claim and acknowledgement are declared transport writes; polling remains an inert read. An unbound waiting intent is claimed atomically by one client. The client reads the exact saved-view revision, restores its data/positions/filter/camera, waits for stable geometry, then submits an actual observed snapshot. The service checks camera, filter, selection and expected positions before storing an `applied` acknowledgement. This attests a technical client observation, never a human identity or human reading.

The initial HTML document and v2 read response carry the same canonical opaque workspace identity. Rendering, view restore and the first change-status baseline must match that document identity. Control waits for both a matching graph and a matching status read. Registration sends exactly `{workspace_id}`; the server compares it with its bound store before creating any lease, returning `workspace_conflict` without registration on mismatch. This also closes a profile switch between the last client-side check and the registration request. A mismatched document is invalidated until reload; a later response cannot revive its old capability or mutate its camera/selection.

A changed saved revision or mismatched observation reports failure instead of success. A lost acknowledgement response is reconciled with the same observation; it does not apply the view again over later user input. A replay of an existing apply operation creates no second intent. Intents expire after 15 minutes and retain their status receipt. Server startup invalidates old client leases and marks outstanding intents `cancelled_restart`.

`graph-view-control.json` is runtime transport state, excluded from portable/workspace backup and profile migration. Saved `graph-views.json` and file evidence remain preserved. Requests are limited to 1,000 receipts, at most 32 short client leases, and the owner-document size budget. The UI retrieves exact stored node identities when loading a view from another bounded graph page; missing nodes cause an explicit failure rather than invented content.
