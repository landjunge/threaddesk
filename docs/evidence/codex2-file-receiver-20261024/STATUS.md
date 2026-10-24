# Codex 2 / ThreadDesk — 24 October 2026

Source: `34b9ea6ad76fd350f898f5068058b4a726880e91`, branch
`feat/codex2-file-receiver-20261024`, based on upstream `64353be` (PR87).
Only the ThreadDesk repository was changed. The dirty main checkout and dirty
Tauri-RC2 worktree were preserved. No other agent was started or interrupted.
The existing coordination thread is `188ce4729a62`; this report supplies evidence
for its appended **Codex 2 / ThreadDesk** entries, not a second work queue.

## Delivered source

- Resumable MCP byte receiver with persisted offsets, exact repeat detection,
  bounded chunks/reservations, explicit thread binding and durable receipts.
- Idempotent record publication recovery after a failed thread-link step.
- Thread-scoped MCP index search and verified local download metadata.
- Existing open route refuses malformed records, missing/changed blobs, digest
  path escapes, symlinks and altered record IDs through controlled errors.
- Exclusive blob publication preserves existing copies; text indexing reads
  only the bounded excerpt rather than loading the whole file first.
- [Versioned integration contract](../../contracts/library-receive-v1.md) for
  the separate KiraBridge adapter, including limits, authorization and failures.

## Verification

The final combined affected test run passed **105 tests**, with one Starlette
httpx deprecation warning:

```sh
PYTHONPATH=src /Users/landjunge/threaddesk/.venv/bin/python -m pytest -q \
 tests/test_library_receive.py tests/test_library_import.py \
 tests/test_library_modules.py tests/test_http_access.py tests/test_mcp.py \
 tests/test_mcp_capability_catalog.py tests/test_mcp_readonly_annotations.py \
 tests/test_release_inputs.py
```

After the last index-temporary-file guard and schema root adjustment, the
directly affected guard/catalog tests passed **6 tests**. These overlap the
combined run; the counts are not additive. The two new guard variants replace
the previous journal-only case. An earlier new-test run had two helper argument
collisions; the helper invocation was corrected and the affected tests passed.
No failing product test was skipped. Tests use synthetic temporary JSON and
SQLite workspaces, including a freshly started real stdio MCP process, receipt
readback and the actual protected UI download route. Original-file preservation
remains covered by the existing import tests.

`git diff --check` and the staged input scan passed. After the code commit,
`scripts/check_release_inputs.py` inspected **346 committed files**, clean.
After fetching origin, `origin/main` remained `64353be` and was verified as an
ancestor of the source commit, so this branch had no base divergence/conflict.
The installed Git lacks `merge-tree --write-tree`; that attempted check was
replaced by the ancestor proof. No merge was performed.

## Local desktop candidate

Built with the existing PyInstaller server spec and `npm ci; npm run build`
(commands executed separately) on native Intel macOS. Both the standalone final
backend and the backend inside the app passed `--self-test` in the implementation's
isolated self-test workspace. The packaged backend matches the built executable
byte for byte. The app initially had no wrapper signature; local ad-hoc signing
was applied to this candidate only, and `codesign --verify --deep --strict`
passed. [build.json](build.json) records hashes and source provenance.

Candidate, retained for review:
`packaging/tauri/src-tauri/target/release/bundle/macos/ThreadDesk.app`.
Build logs remain under ignored `.runtime/`. No installed app was replaced.
The graphical wrapper was not launched because it selects the existing home
workspace. A source/build/self-test result is not graphical user acceptance.
No Apple notarization, Windows/Apple Silicon build or public release is claimed.
The existing shell version is 0.1.2; the baseline Python project metadata still
uses 0.1.1rc1 and needs release-version alignment before distribution.

## Remaining gates and boundaries

- KiraBridge's loaded catalog has no streaming adapter for this new contract.
  Authentication, effective workspace/thread/transfer authorization and live
  end-to-end acceptance must be completed in that separate repository. The
  active bridge process/configuration and old queued tasks were not changed.
- The existing portable-backup allowlist excludes `library-files`, including
  copies and receipts. Library backup/restore is still open; no originals or
  workspaces were removed. Receipt durability is not a backup promise.
- Search indexes metadata and bounded supported text only. PDF/Office/media
  content extraction, exhaustive pagination and an OS filesystem sandbox are
  outside this implementation; the contract states these limits.
- No PR or merge was created. No complete-suite/CI/independent-review acceptance
  is claimed. The repository workflow requires complete browser acceptance
  twice and native Windows backup checks before acceptance; release publication
  also requires native artifacts. These gates remain for an approved PR/merge.
  The GitHub protection endpoint returned `404: Branch not protected`; this
  does not waive the user's explicit review and approval requirement.

The authorized source branch was committed and pushed. No speech module was
added or made mandatory. The integration contract is the next input for Codex 1;
this session does not implement the KiraBridge side.
