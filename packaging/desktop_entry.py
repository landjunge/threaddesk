"""ThreadDesk desktop entry point for packaged applications."""
from __future__ import annotations

from contextlib import contextmanager
from html import escape
import socket
import sys
import threading
import time
from urllib.request import ProxyHandler, build_opener

from threaddesk.services.desktop_runtime import desktop_listener, isolated_self_test


def free_port() -> int:
    """Diagnostic compatibility helper; startup reserves its socket instead."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def urlopen(url: str, timeout: float = 3.0):
    """Local readiness checks must never use an environment HTTP proxy."""
    return build_opener(ProxyHandler({})).open(url, timeout=timeout)


def wait_until_ready(url: str, timeout: float = 15.0, thread=None) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if thread is not None and not thread.is_alive():
            raise RuntimeError("Der lokale ThreadDesk-Server wurde unerwartet beendet.")
        try:
            with urlopen(url, timeout=0.5) as response:
                if response.status == 200:
                    return
        except OSError:
            pass
        time.sleep(0.1)
    raise RuntimeError("ThreadDesk konnte nicht gestartet werden.")


@contextmanager
def running_server(listener):
    import uvicorn
    from threaddesk.ui.server import create_app

    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(
        create_app(), host="127.0.0.1", port=port, log_level="error",
    ))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]},
                              daemon=True, name="threaddesk-server")
    thread.start()
    url = f"http://127.0.0.1:{port}"
    try:
        wait_until_ready(url + "/", thread=thread)
        yield url
    finally:
        server.should_exit = True
        thread.join(timeout=10)
    if thread.is_alive():
        raise RuntimeError("ThreadDesk konnte den lokalen Server nicht sauber beenden.")


def self_test() -> int:
    with isolated_self_test():
        # Resolve the store only after replacing the real data-directory setting.
        from threaddesk.ui.server import _svc
        with desktop_listener(_svc().store) as listener, running_server(listener) as url:
            with urlopen(url + "/migration?lang=en", timeout=3) as response:
                page = response.read().decode("utf-8")
                assert response.status == 200
            assert 'data-testid="migration-center"' in page
            assert 'lang="en"' in page
            for asset in ("app.js", "map.js", "style.css"):
                with urlopen(url + "/static/" + asset, timeout=3) as response:
                    assert response.status == 200 and response.read(), asset
    print("ThreadDesk desktop package and migration page: OK; isolated workspace and bundled assets checked")
    return 0


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()
    import webview
    from threaddesk.ui.server import _svc

    try:
        with desktop_listener(_svc().store) as listener, running_server(listener) as url:
            webview.create_window(
                "ThreadDesk", url + "/", width=1360, height=900,
                min_size=(940, 640), background_color="#0d0e13",
            )
            webview.start()
        return 0
    except Exception as exc:
        # Packaged apps often have no visible console. Show an actionable message.
        message = escape(str(exc))
        webview.create_window("ThreadDesk – Start nicht möglich", html=(
            '<html lang="de"><meta charset="utf-8"><body>'
            '<h1>ThreadDesk konnte nicht starten</h1><p>' + message + '</p>'
            '<p>Deine gespeicherten Threads werden nicht zurückgesetzt.</p></body></html>'
        ), width=640, height=360)
        webview.start()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
