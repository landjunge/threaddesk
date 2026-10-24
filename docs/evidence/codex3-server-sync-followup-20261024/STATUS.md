# Codex 3 follow-up — Desktop, inventory, Linux/TLS and restore

Source acceptance snapshot, 24 October 2026. The existing branch is
`feat/codex3-server-sync-20261024`; original source `1bc13de` was reused.
No new branch, duplicate receiver, KiraBridge change, installed-app replacement
or productive import. Only this worktree was edited. Both existing project and
coordination whiteboards contain progress and review findings with readback.

## Integration and supported behavior

Codex 2 PR88 was inspected before development. Its committed fixes `f4070aa`
and `55aa6d8` were integrated after code comparison; its active worktree was
preserved. After Codex 2 merged PR88, main merge `80453ff` was incorporated
through local integration `58dc966`. There were no textual conflicts. The
receiver/library contract was not reimplemented or changed by this follow-up.

Native subagents worked in disjoint modules: inventory/metadata, discovery/client,
and backup/Linux acceptance. Root built the Desktop adapter, integration, UI and
reviewed the results. Independent read-only reviews found and led to fixes for
policy-generation races, workspace grant containment, pristine bootstrap proof,
and portable identity after restore. No unresolved concrete auth/data-loss
blocker was reported in the reviewed scope; required PR review/CI still applies.

A final operational review found full metadata receipts would be appended on
every idle poll. Before publication this was corrected with authenticated
conditional GET/ETag and an identical-200 fallback, with no receipt/snapshot/
checkpoint writes when both states are unchanged. Pending uncertain requests
still replay. Dedicated JSON/SQLite checks verify repeated idle polls leave
journal sizes unchanged. Desktop status also polls its observed state without
replacing edited form fields, and bounded error details redact credentials.

- Existing Desktop threads bind through **Server und Abgleich**. Connection
  credentials are private (0700 directory/0600 files), absent from metadata/views.
  Omitted server project ID uses an idempotent deterministic binding receipt.
  Bootstrap seeds only an unused checkpoint and cannot adopt unproven existing
  metadata as blank. Automatic sync/reconnect runs while Desktop is open.
- Notes, title, description, status, prompts, project/task nodes, relationships,
  project membership and append-only whiteboards replicate in both directions.
  Three-way merges, durable operation replay, previous snapshots and visible CAS
  conflict selection retain changed values. No agent/task execution hooks run.
  JSON and SQLite Desktop workspaces are covered. Portable namespace identity is
  durable across relocation/restore, preventing duplicate nodes and board entries.
- Discovery reuses explicit local file/directory grants plus the selected tree.
  Static Python, JS/TS, Markdown, HTML/CSS and manifests are inspected without
  executing code. External sources have stable logical mappings; safe server
  edits update their original authorized targets with recovery on the same
  filesystem. Exact-file grants do not allow siblings; remote metadata cannot
  grant new host reads, unknown namespaces or revoked destinations.
- New files are re-enumerated. Missing, unsafe, oversized and unresolved dynamic
  dependencies block readiness. This is static analysis with explicit authority,
  not a proof for arbitrary generated program behavior or external services.
- Cold backups cover the complete server tree: credentials, core metadata,
  snapshots, tasks, whiteboards, immutable bytes/history, conflicts, partial chunks
  and receipts. ASGI lifespan holds the exclusive lifecycle lock; disabled
  lifespan cannot serve the API. Backup refuses a live server. Restore validates
  before publication to a NEW directory, preserving originals and old archives.

## Targeted verification

The combined affected run passed **88 tests** (new server modules, Desktop
binding, actual API, HTTP access and directly affected i18n guards). After the
bounded metadata size adjustment and idle-journal fix, the **18 directly affected metadata tests**
passed, including full 100000-emoji notes on JSON and SQLite. One actual HTTP
Unicode/CAS/append-only test then passed with the larger body boundary. These
counts overlap and must not be added. One upstream Starlette/httpx deprecation
warning; no skipped failures or weakened assertions.

During integration an earlier affected run had 138 passing / 3 new i18n failures.
Labels, placeholder and dynamic-state catalog coverage were corrected and the
failed checks passed. The guard for unsafe POST routes now includes the new
protected Desktop action; authentication/CSRF assertions were retained.

Focused coverage includes uncertain replies, changed pending uploads, metadata
and file conflicts, JSON/SQLite replay, owned-project mapping, restore at a new
path, stable origins, external original destinations and revoked grants,
symlink/FIFO/path aliases, credential privacy, stale policy result CAS, private
checkpoint containment, corrupted/hostile backup archives and resource bounds.

## Actual browser and Desktop acceptance

The final CLI + Chromium run passed: server login/session/logout, project and
offline option, verified upload, editing/history, core notes and task entries.
It additionally exercised the actual protected Desktop form, automatic Desktop
to server and server to Desktop notes, existing tasks/whiteboards, explicitly
attached external file mapping, original preservation and conflict selection in
the server browser. No JavaScript page errors.

[Browser receipt](browser.json), [server screenshot](browser.png),
[Desktop screenshot](desktop.png). Command:

```sh
PYTHONPATH=src python packaging/server/check_browser.py --with-desktop \
  --output-dir /tmp/threaddesk-browser-evidence
```

An existing Chromium binary can be passed with `--browser-binary`. A first
follow-up harness start rejected macOS `/var`'s system symlink; only the new
temporary harness directory was canonicalized. Product path guards were retained.
Native Tauri distribution builds are checked separately by repository CI; this
browser proof is not a claim of GUI testing on every native platform.

## Actual Linux, verified TLS and complete restore

The mandatory final image build and acceptance passed on **Linux x86_64**,
unprivileged/read-only root filesystem, isolated network and synthetic private
data. Docker used the already running Colima runtime through an explicit context;
no global context switch or foreign container stop. A development OrbStack start
was also issued during initial runtime discovery; neither runtime was stopped.
Only the harness's own containers were cleaned up.

Image: `sha256:4e1083d3ccf0f59bed90a6cd649a5b6b338565dc6dda2707dccfc601ec35be52`.
Production input content SHA256:
`69a72d72229071c7595d022b944d9bebebcbfc73ed385644fda5ba70851591dc`.
The 148 input fingerprints were compared after acceptance; none changed.
[Source manifest](source-manifest.json), [Linux receipt](linux.json),
[complete build/acceptance log](linux-acceptance.log).

Verified TLS used an ephemeral private CA and normal certificate validation;
default trust and plaintext were refused. Two replicas demonstrated bidirectional
file edits and conflict/original retention. The real app lifecycle refused live
backup; restart retained confirmed partial offsets. Full backup restored to a
new directory, including credentials, metadata snapshots, whiteboards, all old
versions/conflicts, chunks, durable file receipts, stable metadata origins and
exact metadata operation replay. Both replicas resumed after restore.

Early setup attempts exposed Colima bind-mount and read-only-copy restrictions;
the harness now streams only its synthetic script/certificates to tmpfs. An
arbitrary 10-second harness stop ceiling was corrected after observing uvicorn
idle TLS shutdown. Final app/harness use a finite graceful shutdown timeout.
The final successful run rebuilt the image; the earlier diagnostic pass was not
substituted for it. Command (Docker daemon required):

```sh
python packaging/server/check_acceptance.py --docker-context colima
```

The new `Server Sync Linux TLS Restore` workflow repeats this acceptance on a
fresh PR image. Deployment to a public domain, public-CA/Caddy operation and
restore on another CPU architecture are not claimed by the isolated proof.

## Merge gates and retained boundaries

The user authorized commit, push, PR and merge after successful required checks.
This file is the source/acceptance snapshot before those external checks. Exact
PR, check-run and final merge SHAs are recorded in both whiteboards and GitHub's
PR timeline after execution; a pending PR is never treated as a completed merge.
No release assets or productive installation are requested by this change.

Limits remain explicit: 64 MiB/file, 1 GiB logical retained contents/user plus
metadata/journal overhead, 1 MiB metadata document, 4 GiB/100000-entry backup.
Unresolved dependencies fail closed. New file destinations remain within current
grants, and no automatic file/version garbage collection is introduced. The
separate pre-existing portable Desktop library backup omission is unchanged;
the complete server backup and Desktop metadata adapter do not conceal it.
