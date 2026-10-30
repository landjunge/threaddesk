"""Read-only canonical revision signature; unrelated receipts do not stale search."""
from pathlib import Path
import sqlite3
from contextlib import nullcontext


def canonical_state(workspace: Path, *, connection=None):
    database = workspace / "threaddesk.sqlite3"
    if connection is not None or database.exists():
        if database.is_symlink() or database.stat().st_nlink != 1:
            raise OSError("unsafe_workspace_database")
        owner = (nullcontext(connection) if connection is not None else
                 sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True, timeout=1))
        with owner as db:
            db.execute("PRAGMA trusted_schema=OFF")
            state = [tuple(db.execute(
                f"SELECT count(*),total(CAST(json_extract(payload,'$.revision') AS INTEGER)),max(updated_at) FROM {table}"
            ).fetchone()) for table in ("threads", "nodes")]
            # Lifecycle writes retain object payloads and revisions. Include
            # their own commit signature so deleted content cannot remain fresh.
            try:
                state.append(tuple(db.execute("SELECT count(*),total(generation),total(CAST(json_extract(payload,'$.revision') AS INTEGER)) FROM trash_entries").fetchone()))
            except sqlite3.OperationalError:
                state.append((0, 0, 0))
            return state
    result = []
    for folder in ("threads", "nodes", "trash"):
        directory = workspace / folder
        if directory.is_symlink():
            raise OSError("unsafe_workspace_directory")
        for path in sorted(directory.glob("*.json")):
            if path.is_symlink():
                raise OSError("unsafe_workspace_document")
            info = path.stat()
            result.append((folder, path.name, info.st_size, info.st_mtime_ns))
    return result
