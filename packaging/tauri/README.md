# ThreadDesk 0.1.1 RC2 (Tauri, Intel macOS)

This release candidate bundles the existing local-first ThreadDesk Python HTTP server with an independent Tauri WebKit window. It does **not** require a Python installation on target machines.

The Tauri build uses its own data directory (the Tauri bundle identifier), not the production `~/.threaddesk`. The old application and user data are not migrated automatically. There is no auto-update endpoint and no remote service.

To build on an x86_64 macOS host:

1. Install the ThreadDesk development dependencies including PyInstaller.
2. From repository root, run `python -m PyInstaller --clean --noconfirm --distpath packaging/tauri/backend/dist --workpath packaging/tauri/backend/build packaging/tauri/backend/ThreadDeskServer.spec`.
3. Run `packaging/tauri/backend/dist/ThreadDeskServer --self-test`.
4. From `packaging/tauri`, run `npm ci` and `npm run build`.
5. Check `src-tauri/target/release/bundle/macos/ThreadDesk.app`, sign locally with `codesign --force --deep --sign -` if needed and package a zip for GitHub release uploads.

No Apple Developer ID signing or notarization is provided. Gatekeeper may require manual user approval. Verify the bundle, bundled backend, and local GUI with a clean test workspace before distributing. This is a release candidate, not a notarized stable release.

