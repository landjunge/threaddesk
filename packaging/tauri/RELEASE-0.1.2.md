# ThreadDesk 0.1.2 — Intel macOS

Ad-hoc signed Tauri shell. It is not Developer-ID signed and not notarized.

## Install

The built app is `packaging/tauri/src-tauri/target/release/bundle/macos/ThreadDesk.app` in the build tree. Copy that bundle somewhere other than the existing installation first. Open it from Finder with the context menu if Gatekeeper blocks the ad-hoc signature.

The app uses `~/.threaddesk`. It does not create a second store and does not migrate or delete that directory.

## Rollback

Quit the new app. Leave `~/.threaddesk` in place. Move the previous `~/Applications/ThreadDesk.app` back if it was replaced. This build does not replace that app by itself.

## Checks before use

The sidecar prints `THREADDESK_URL http://127.0.0.1:<port>` and the window loads that address. Library copies live under `~/.threaddesk/library-files/`.
