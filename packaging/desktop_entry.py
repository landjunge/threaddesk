"""ThreadDesk desktop entry point used by the packaged macOS and Windows apps."""

from __future__ import annotations

import socket
import sys
import threading
import time
from urllib.request import urlopen


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_until_ready(url: str, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=0.5) as response:
                if response.status < 500:
                    return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("ThreadDesk konnte nicht gestartet werden.")


def main() -> int:
    if "--self-test" in sys.argv:
        import uvicorn

        from threaddesk.ui.server import create_app

        port = free_port()
        app = create_app()
        server = uvicorn.Server(uvicorn.Config(
            app, host="127.0.0.1", port=port, log_level="error",
        ))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        try:
            migration_url = f"http://127.0.0.1:{port}/migration?lang=en"
            wait_until_ready(migration_url)
            with urlopen(migration_url, timeout=2) as response:
                page = response.read().decode("utf-8")
            assert response.status == 200
            assert 'data-testid="migration-center"' in page
            assert 'lang="en"' in page
        finally:
            server.should_exit = True
            thread.join(timeout=10)
        assert not thread.is_alive()
        print("ThreadDesk desktop package and migration page: OK")
        return 0

    import webview

    from threaddesk.ui.server import run

    port = free_port()
    url = f"http://127.0.0.1:{port}/"
    server = threading.Thread(
        target=run,
        kwargs={"host": "127.0.0.1", "port": port},
        daemon=True,
        name="threaddesk-server",
    )
    server.start()
    wait_until_ready(url)
    webview.create_window(
        "ThreadDesk",
        url,
        width=1360,
        height=900,
        min_size=(940, 640),
        background_color="#0d0e13",
    )
    webview.start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
