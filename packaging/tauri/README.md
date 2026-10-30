# ThreadDesk 0.2.0 (Tauri, Intel macOS)

This release candidate bundles the existing local-first ThreadDesk Python HTTP server with an independent Tauri WebKit window. It does **not** require a Python installation on target machines.

The window opens the existing workspace at `~/.threaddesk` or the explicitly selected profile. There is no auto-update endpoint. The local application works offline; optional room/server sync remains explicitly configured. Local builds are ad-hoc signed.

To build on an x86_64 macOS host:

1. Install the ThreadDesk development dependencies including PyInstaller.
2. From repository root, run `python -m PyInstaller --clean --noconfirm --distpath packaging/tauri/backend/dist --workpath packaging/tauri/backend/build packaging/tauri/backend/ThreadDeskServer.spec`.
3. Run `packaging/tauri/backend/dist/ThreadDeskServer --self-test`.
4. From `packaging/tauri`, run `npm ci` and `npm run build`.
5. Check `src-tauri/target/release/bundle/macos/ThreadDesk.app`, sign locally with `codesign --force --deep --sign -` if needed and package a zip for GitHub release uploads.

No Apple Developer ID signing or notarization is provided. Gatekeeper may require manual user approval. Verify the bundle, bundled backend, and local GUI with a clean test workspace before distributing. This is a release candidate, not a notarized stable release.

## Visible version and source identity

The shared header displays the package version and the first seven characters of the source commit. Both PyInstaller specifications run `scripts/write_build_info.py` before collecting resources. It records the current commit, whether the checkout contains local changes, and the UTC build identifier in an ignored package resource. The running app reads that resource without executing Git or accessing a user workspace.

Commit the intended source before building a distributable package. A clean checkout produces a label such as `v0.1.2 · abcdef0`; an uncommitted checkout adds `+lokal`. A source launch without valid packaged metadata says `Quellstand` rather than claiming a commit. Keep the Python package version, Tauri configuration, npm package and Cargo package aligned when changing versions.

Before replacing an installation, preserve the previous app and workspace, run the packaged self-test, and check the app with a separate HOME containing a workspace copy. Verify the actual header and the thread/graph/whiteboard counts, then compare source hashes and embedded build metadata. Install only the tested bundle. Publishing that exact source commit afterwards keeps the installed label traceable to GitHub.

## Workspace response ordering

Independent editor forms may finish in a different order from their requests. The UI suppresses superseded workspace responses so that an older note-save response cannot replace a later snapshot restore or thread selection. Requests still finish normally and write failures remain visible. The browser regression delays a real note-save reply until after the restore swap and verifies the restored note again after a server restart.

