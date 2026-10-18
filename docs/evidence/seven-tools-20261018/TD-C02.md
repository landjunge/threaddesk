# TD-C02 – issued-source/run binding

Auftrag `seven-tools-build-20261018-1833`, Worker `threaddesk_m1`.
Stacked source branch `feat/seven-tools-m2-20261018` on the reviewed M1 contract.
No real user workspace, runtime, Bridge configuration or external agent touched.

## Implementiert / implemented

- Idempotent `issue_handoff`, read-only lookup by issue operation or handoff ID,
  and persistent exact accepted-run binding. Original ThreadDesk task IDs remain
  intact; no lossy colon replacement, new dispatch or duplicate queue.
- Each emitted/issued handoff stores its actual payloadhash and separate source
  snapshot/threadrevision/contenthash. Export alone does not change thread revision.
- Fixed operator source roots optionally enable bounded no-follow regular-file
  hashes; no configuration means unsupported, no file opened. Current boundary:
  max16 roots,32 files,1MiB/file,4MiB total; excess/unsafe/unreadable remain unknown.
  File hashes are content evidence, not Git provenance or function tests.
- Strict new return import validates the issued basis before its first delivery,
  exact handoff/thread/task/run/worker and current sources. Missing registrations,
  run binding, changed basis or different scope/run/hash are errors.
- Old unbound imports are preserved as legacy_unbound/unknown. A legacy receipt
  cannot turn into a strict receipt through a repeated ID. Delivery remains
  unverified; existing explicit user review and whiteboard remain in use.
- Bound waiting questions and replies persist with the existing whiteboard.
  Same identities/content repeat once, changed content conflicts; reply requires
  the actual recorded waiting question. Reply status is recorded_for_run, not
  unproven delivery to a running model. No automatic adapter resume is claimed.
- SQLite schema6 adds issued records; JSON uses the M1 resulting-state commit.
  Issue/snapshot and question/whiteboard are transactional. Inbox decisions are
  serialized; migration/backups preserve records. SQLite whiteboard inserts join
  an existing transaction instead of starting/committing an unrelated one.
- Existing DE/EN README and MCP contract extended; no second conversation UI.

## Prüfungen / checks

Isolated synthetic workspaces on both JSON and SQLite; no real accounts/secrets,
paid-provider calls, new CLI agent or live ChatGPT session.

- M2 issuance/inbox plus existing MCP/characterization/storage/JSON-migration:
  **46 passed** before the final bounded-source guard case.
- Focused question/answer, first stale source, scope and waiting-state probes:
  **21 passed** (M2 + inbox + old-v3 upgrade case).
- Source-count/oversize/FIFO/no-root non-opening and final file-change/question
  probes were run separately after the bounded-source guard adjustment; result
  **5 passed** in0.30s (including both backends for file/question cases).
- Ruff format/check on new issued_handoffs implementation and its tests.

A real source-file change with unchanged thread revision is rejected as
return_stale_source. The first stale return after a changed thread is rejected
with an empty inbox: no earlier newer return is needed. Foreign thread/task/
handoff/run/worker or changed binding owner/scope cannot be attached. Restart
lookup retains issue identity; identical issue returns the same handoff/snapshot.

## Grenzen / limits

This is implemented/tested source, not deployment, packaged desktop, integrated
KiraBridge workflow acceptance or user acceptance. Bridge must independently
prove actual dispatch, waiting/resume, cancellation and session identity. Existing
local stdio trust/profile boundaries apply; principal_ref/operator_scope are
configured audit references, not new authenticated tenants. The file-only source
adapter does not attest repository commit, entire repo, function, legal rights
or file contents outside fixed operator roots. Unsupported sources stay partial
unverified. Schema6 needs a current SQLite writer. Upgrade older JSON writers
before concurrent mutable use; M1's observed-content anchor is not an OS sandbox.

TD-C03, design PR66 and a separate desktop release remain independent; no further
stage started after the user's new Bridge-rights priority.
