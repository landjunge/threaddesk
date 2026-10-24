"""Standalone localhost-only backend for the Tauri macOS bundle."""
from __future__ import annotations

import sys
from threaddesk.storage.portable_backup import base_root
from threaddesk.storage.json_store import JsonStore
from threaddesk.services.desktop_runtime import desktop_listener
from packaging_desktop_entry import running_server, self_test


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()
    with desktop_listener(JsonStore(base_root())) as listener:
        with running_server(listener) as url:
            print("THREADDESK_URL " + url, flush=True)
            sys.stdin.buffer.read(1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

