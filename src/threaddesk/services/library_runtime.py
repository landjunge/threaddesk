"""One bounded worker for explicitly registered source roots in the active profile."""
from threading import Event, Thread

from threaddesk.services.library_index import LibraryIndex
from threaddesk.services.library_refresh import refresh_existing
from threaddesk.services.library_watch import LibrarySourceWatch


class LibraryRuntime:
    def __init__(self, store_factory, interval=5.0):
        self.store_factory = store_factory
        self.interval = max(1.0, interval)
        self.stopped = Event()
        self.thread = None
        self.last_error = ""

    def tick(self):
        store = None
        try:
            store = self.store_factory()
            if (store.workspace_path / "library-watch.json").is_file():
                LibrarySourceWatch(store).poll_once()
            index = LibraryIndex(store.workspace_path / "library-files")
            if index.path.is_file() and index.status()["status"] == "stale":
                refresh_existing(store)
            self.last_error = ""
        except Exception as exc:
            # Per-source failures are durable watch receipts. A broken optional
            # projection must not take down normal thread or browser operations.
            self.last_error = type(exc).__name__
        finally:
            if store is not None and hasattr(store, "connection"):
                store.connection.close()

    def start(self):
        if self.thread is not None:
            return
        def loop():
            while not self.stopped.wait(self.interval):
                self.tick()
        self.thread = Thread(target=loop, name="threaddesk-library-watch", daemon=True)
        self.thread.start()

    def stop(self):
        self.stopped.set()
        if self.thread is not None:
            self.thread.join(timeout=2)
