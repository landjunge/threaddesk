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

The first PR head `b824ae3` passed native Windows backup, all three native
package builds and the new Linux/TLS/restore CI. Complete CI found 1110 passing
tests and one template guard failure: a literal escape inside a Jinja join.
Formatting was moved into the Python view; the existing guard was retained.

Automated PR review then correctly identified two issues: imported references
could become grants on a later sync through percent-decoding, and moving the
selected directory reused a path-bound file checkpoint. Private owner grants
are now independent from merged context, literal paths retain their spelling in
discovery AND cache validation, explicit local add/remove actions update grants,
and file checkpoint namespaces include the selected root. A native-team scope
review also found deterministic imported IDs could overwrite an object moved out
of this project; creation now refuses409 and the transaction retains foreign
values. **53 directly affected checks passed** for these corrections, including
two-run real-API private-file injection, directory relocation, cached grant
revocation, foreign node/relation preservation and the original template guard.
These results overlap the earlier checks. All required CI must pass again for
the correction head; the older head's successful jobs do not substitute for it.
After separating authority, another **29 directly affected checks passed** with
new local references kept as validation-only requirements: an attachment added
outside the protected grant action blocks readiness and is not silently omitted
or uploaded. Independent read-only review found no critical authority/data-loss
flaw in the final grant/reference/cache changes. Counts again overlap; no broad
local suite was repeated for this correction.

Head `7ce4003` subsequently passed the required complete CI **1116 tests twice**,
native Windows backup (164 cases), all three native builds and Linux/TLS/restore.
The final review gate reported two further valid P2 cases before merge: a
browser-aborted upload would reuse its cancelled ID indefinitely, and the
512 KiB body boundary rejected valid larger inventories. Confirmed cancellation
now allocates one persisted replacement ID per run, while uncertain replies keep
their checkpoint. Manifests now have one shared bounded 96 MiB endpoint limit;
transfer blocks retain their smaller bounds. **13 client tests** passed including
restart after cancellation/lost replacement acknowledgement and bounded repeated
cancellations; **5 API tests** passed including real 5000-file header+stream
manifests, stream-limit rejection and unchanged upload limits. These overlap
earlier results. The correction image was rebuilt and accepted again; its source
fingerprints below include both fixes. Required CI must validate the new head.

Head `9210dab` also passed every required CI gate, including the complete suite
twice. Three later review findings were corrected before merge: the shipping
Caddy proxy now matches the application's endpoint bounds; the browser durably
replaces a confirmed aborted transfer ID with at most two begin attempts; and a
Desktop binding retains its reporting identity across root-specific checkpoints.
Only verified committed common revisions seed a pristine relocated checkpoint;
pending uploads and source authority never migrate. Different credentials or
projects do not inherit bases. Real manager tests cover edits before/after the
first relocated sync, concurrent server changes, retained originals/history,
hashed/legacy identity migration and one remaining manifest reporter. A real
browser reload also exposed replay of the original blank-project configure POST;
its deterministic automatic binding now retains the same project/device safely.
The targeted identity/client run passed **23 tests**; the final combined
identity/client/Desktop run passed **27 tests**, overlapping earlier counts.
The final real Chromium/Desktop acceptance passed, including aborted browser
upload retry, retained cancellation receipt and automatic bidirectional metadata.
The shipping Caddy acceptance additionally sends 19000-file manifests with both
Content-Length and chunked transfer, a Unicode metadata pair above the old proxy
cap, and checks that ordinary transfer bounds still reject oversized requests.
Required CI must still pass on the final correction head.

Two further concrete review cases were corrected before merge: competing file
heads now acknowledge the verified local contribution, allowing a later explicit
Browser resolution to replace unchanged local bytes safely. New local edits still
form a conflict. The exact synthetic `browser-server` reporter is now a live
server view, including interpretation of older persisted snapshots and stale
in-flight posts; genuine replica requirements remain unchanged. Status adds no
journal writes. Protected API regressions cover resolution followed by process
restart, both unchanged and newly edited local files, recovery copies and full
history; **15 client tests passed**. The combined client/store/server-view run passed **22 tests**. Dedicated
server-view regressions check
later Desktop writes, stale browser posts, idle journal stability, real replica
disagreement, conflicts and integrity. Fresh Linux/Proxy and live Browser/Desktop
acceptance are repeated for these source corrections; the live Browser/Desktop
sequence passed with original recovery and all three file versions retained.
Final-head CI still applies.

The subsequent review exposed a deferred Browser project-response race and
an exact inventory-capacity boundary error. Selection generations now guard
thread reads, save replies and collections; metadata controls stay disabled while
loading, and a stale reply cannot overwrite another project or its revision.
A deterministic test executes the actual JS with deferred reads/saves, equal
initial revisions, loading submission and an A/B/A selection sequence. Discovery
now reports overflow only for an additional eligible distinct source beyond
MAX_FILES, not for exactly MAX_FILES. Nested/empty directories, filtered entries
and duplicate grants have boundary coverage. **11 directly affected checks**
passed, and the complete real Browser/Desktop acceptance passed again. The fresh
Linux/Proxy receipts below cover these final sources. Final-head CI remains
mandatory before merge.

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

Image: `sha256:4025ea3685545f7c8bfd191a2bdee8d9303de9387f293b228bd5578be9bcb087`.
Production input content SHA256:
`a59afdc6752ac58b63f0a9f992ebe1cbcc4ec98fdcfd31d27e94f272282ce7d2`.
The 150 input fingerprints (including the shipping Caddyfile) were compared after acceptance; none changed.
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
fresh PR image, followed by the actual shipping Caddy proxy acceptance.
The latter passed with the same fresh app image and official Caddy image,
CA-verified TLS, app unpublished, and only a random Caddy port on host loopback.
Both 3,705,052-byte/19000-file manifest wire modes returned 200; the
2,400,600-byte metadata pair returned 200 without truncation; oversized ordinary
requests returned 413 in both modes. [Proxy receipt](proxy.json) and
[complete proxy log](proxy-acceptance.log) record the immutable image IDs and
shipping configuration hash. Deployment to a public domain, public-CA issuance
and restore on another CPU architecture are not claimed by these proofs.

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
