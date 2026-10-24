# Codex 3 — Server & Sync, 24 October 2026

First reviewed development milestone, **not completion of the full revision 3
product plan**. Read project `c2d4c7bc985a` revision 3 and coordination
`188ce4729a62` revision 11, including all Codex 2 entries, before implementation.
Authoritative coordination remains those two existing whiteboards; this file
records source and verification evidence, not a replacement task board.

## Isolation and decisions

- Worktree: `/Users/landjunge/threaddesk-worktrees/codex3-server-sync-20261024`.
  Branch: `feat/codex3-server-sync-20261024`, base Codex 2's `0aa268a`.
- Original dirty checkout, Codex 2's clean worktree and KiraBridge source/runtime
  were preserved. No external agent/window input, import or installed-app change.
- Native subagents: `inventory` (read plan, implement SyncStore, independent
  review), `sync_client` (client and focused data-loss checks), `linux_packaging`
  (installation templates and independent auth review). Root implemented API,
  browser, integration and reviewed each result in the shared isolated worktree.
- Separate authenticated server adapter; never mount the desktop's deliberately
  localhost-only HTTP application. Shared ThreadService/JsonStore holds project
  threads, metadata and append-only whiteboards in server-selected user roots.
- [Versioned contract](../../contracts/server-sync-v1.md) was posted to both
  whiteboards before parallel implementation. Codex 2's library MCP contract and
  receiver remain unchanged. Contract publication is not a claim that Codex 1 or
  Codex 2 has accepted or implemented an adapter.

## Implemented

- Browser login using operator-provisioned random access tokens, hashed private
  credential configuration, signed expiring HttpOnly sessions, exact origin,
  CSRF, host and HTTPS boundaries; Bearer access for the client. User and project
  scope applies to every transfer/revision operation. Public TLS uses a separately
  configured trusted reverse proxy; explicit loopback HTTP is development only.
- Per-project **Auch offline**. Default declarations contain paths, size and
  hashes only. Disabled projects reject new byte publication; existing versions
  and originals remain. Status includes missing files, bytes, conflicts and last
  declaration time. Readiness requires a complete declared, integrity-checked
  inventory without unresolved issues or transfers.
- Durable transactional SQLite chunk/resume state, exact replay, immutable file
  versions, SHA-256 verification, stale-base branching and CAS conflict choice.
  History remains readable after conflict resolution. Unfinished transfers can
  be aborted without deleting completed versions; absent-ID tombstones protect
  against delayed begins and free reservations safely.
- Local Linux/macOS client enumerates the explicitly selected tree each time,
  including later files; recognized Markdown/HTML/CSS and core file references
  detect missing/out-of-tree dependencies. No traversal of symlinks, VCS internals
  or secret-shaped paths. Descriptor-bound traversal prevents ancestor symlink
  escapes and refuses FIFO/special files before reading.
- Bidirectional file changes use a private durable checkpoint and last common
  revision. Concurrent bytes remain on both sides; local displaced inodes and
  additional server conflict copies have private path/hash/revision sidecars.
  No automatic file deletion, history collection or execution.
- Browser project creation, notes with revision CAS and previous snapshots,
  task/whiteboard entries, file uploads, text editing, download/history and
  conflict choice. Independent install extra and console entry points; Docker,
  Compose+Caddy and user-systemd/venv templates plus German instructions.

Bounds: 64 MiB/file, 256 KiB/chunk, 32 concurrent transfers, 512 MiB reservations,
1 GiB retained logical content plus reservations/user. SQLite overhead, metadata,
copies and journals require additional physical disk space. Data directories
are trusted against a hostile same-user administrator; this is not an OS sandbox.

## Verification

Final targeted run, after cancellation, recovery mapping, schema/status and API
changes: **20 passed**, one upstream Starlette/httpx deprecation warning, no
skips. Tests use synthetic temporary workspaces only:

```sh
PYTHONPATH=src python -m pytest -q \
  tests/test_server_sync_store.py tests/test_server_sync_client.py \
  tests/test_server_sync_api.py
```

Coverage is intentionally limited to the new boundaries: restart/replay/receipts,
checksum corruption, quotas and reservations, stale/missing-base conflicts and
retained history, missing dependencies, path aliases and symlink/FIFO races,
local publication/recovery failure, lost chunk/commit replies, changing files
during interrupted transfers, TLS/checkpoint identity, tenant/project isolation,
cookie/CSRF/origin controls and shared-core metadata CAS. Real FastAPI calls with
two independent clients verify new files, restart and conflict preservation.

Final real CLI + Chromium acceptance passed in an isolated loopback development
server: login, project, offline checkbox, verified upload/readiness, text edit,
two retained versions, notes, task, session reload and logout. No JavaScript page
errors. [Browser receipt](browser.json), [screenshot](browser.png). Reproducible:

```sh
PYTHONPATH=src python packaging/server/check_browser.py \
  --output-dir /tmp/threaddesk-browser-evidence
```

Use `--browser-binary /path/to/chromium` for an already installed browser. The
first attempt could not find Playwright's expected revision; the second harness
attempt used string evaluation forbidden by the product CSP. The harness was
corrected to locator assertions; the CSP was retained. Both final browser runs
passed; they are not two independent native-platform acceptance runs.

Wheel built and inspected: modules, web assets, server dependency extra and both
console scripts present. [Receipt](wheel.json). No freshly installed dependency
environment or Linux package runtime is claimed. JavaScript syntax, installer
shell syntax, Compose configuration and diff whitespace checks passed.
Independent final read-only review found no new concrete authorization/data-loss
blocker in the reviewed implementation. This does not replace full PR review/CI.

No full repository test suite was run; shared desktop/receiver files were not
changed. No unnecessary repeated broad checks. Earlier focused counts overlap
the final 20 and must not be added to it.

## Remaining plan / blockers

1. Native Linux image/install/TLS/restore acceptance: local Docker daemon socket
   was unavailable (`~/.orbstack/run/docker.sock`). Compose validates structurally;
   no image build, production server or unrelated service was started.
2. Native Desktop per-project controls and binding existing desktop workspaces
   to this client remain an integration. Desktop metadata/tasks/whiteboards do
   not yet synchronize bidirectionally; browser-side shared core is implemented.
3. Arbitrary runtime/program-language/out-of-tree dependencies cannot be proved
   complete by this scanner. UI explicitly describes the declared inventory
   boundary. External mappings and richer dependency adapters remain work.
4. Conflict selection preserves all bytes; a still-different local version must
   be consciously reconciled. Old device manifests conservatively prevent ready
   until refreshed. Token rotation/device retirement and explicit version GC
   need separate lifecycle work; no destructive shortcuts were introduced.
5. Consistent backup/restore, broader native/browser acceptance and required CI/
   independent approval remain release gates. Existing portable desktop backup
   exclusion of Codex 2's `library-files` remains open and unchanged.
6. Distribution version alignment remains open: inherited Python metadata is
   `0.1.1rc1`; no new release version, push, merge or publication performed.

Next integration contract: bind an explicitly chosen desktop project/workspace
to this API and agree on metadata/conflict ownership with Codex 2, without
changing Codex 1's KiraBridge contract or blocking either independent branch.
