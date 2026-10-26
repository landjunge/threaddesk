"""Run with Python >=3.9 and PYTHONPATH=<reviewed ThreadDesk>/src.
Creates only TemporaryDirectory workspaces and never opens production data.
"""
from tempfile import TemporaryDirectory
from pathlib import Path
from threaddesk.api.service import ThreadService
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore
from threaddesk.services.thread_management import manage
from threaddesk.core.errors import ManagementError


def main():
    for cls in (JsonStore, SQLiteStore):
        with TemporaryDirectory(prefix="td-arch-") as tmp:
            svc = ThreadService(store=cls(Path(tmp)))
            seen = []
            svc.bus.on("*", lambda name, payload: seen.append(name))
            try:
                manage(svc, {
                    "operation_id": "rollback-create",
                    "action": "create",
                    "expected_revision": 0,
                    "data": {"title": "Roll back", "parent_thread_id": "missing"},
                })
            except ManagementError as exc:
                print(cls.__name__, exc.code,
                      "persisted_threads=", len(svc.list()), "events=", seen)
            finally:
                if hasattr(svc.store, "connection"):
                    svc.store.connection.close()


if __name__ == "__main__":
    main()
