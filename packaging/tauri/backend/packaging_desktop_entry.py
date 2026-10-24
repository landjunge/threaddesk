"""Access shared packaged-server support without importing desktop GUI components."""
from __future__ import annotations

from contextlib import contextmanager
import socket
import sys
import threading
import time
from urllib.request import ProxyHandler, build_opener


def urlopen(url, timeout=3):
    return build_opener(ProxyHandler({})).open(url, timeout=timeout)


def wait_until_ready(url, timeout=20, thread=None):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if thread is not None and not thread.is_alive():
            raise RuntimeError("ThreadDesk backend stopped before it was ready")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            with urlopen(url, timeout=remaining) as response:
                if response.status == 200:
                    return
        except OSError:
            pass
        if deadline - time.monotonic() > 0:
            time.sleep(min(0.1, deadline - time.monotonic()))
    raise RuntimeError("ThreadDesk backend startup timed out")


@contextmanager
def running_server(listener):
    import uvicorn
    from threaddesk.ui.server import create_app
    server = uvicorn.Server(uvicorn.Config(
        create_app(), host="127.0.0.1", port=listener.getsockname()[1],
        log_level="error", log_config=None, proxy_headers=False))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]},
                              daemon=True, name="threaddesk-tauri-backend")
    thread.start()
    url = "http://127.0.0.1:" + str(listener.getsockname()[1])
    try:
        wait_until_ready(url + "/", thread=thread)
        yield url
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def self_test():
    from threaddesk.services.desktop_runtime import isolated_self_test, desktop_listener
    from threaddesk.storage.portable_backup import base_root
    from threaddesk.storage.json_store import JsonStore
    with isolated_self_test():
        with desktop_listener(JsonStore(base_root())) as listener:
            with running_server(listener) as url:
                for path in ("/", "/migration?lang=en", "/static/app.js", "/static/style.css"):
                    with urlopen(url + path, timeout=4) as response:
                        assert response.status == 200 and response.read(), path
    print("ThreadDesk Tauri backend self-test: OK", flush=True)
    return 0

