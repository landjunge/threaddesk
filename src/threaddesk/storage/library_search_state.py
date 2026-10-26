"""Read-only canonical revision signature; unrelated receipts do not stale search."""
from pathlib import Path
import sqlite3


def canonical_state(workspace: Path):
    database = workspace / "threaddesk.sqlite3"
    if database.exists():
        if database.is_symlink() or database.stat().st_nlink != 1:
            raise OSError("unsafe_workspace_database")
        with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True, timeout=1) as db:
            db.execute("PRAGMA trusted_schema=OFF")
            return [tuple(db.execute(
                f"SELECT count(*),total(CAST(json_extract(payload,'$.revision') AS INTEGER)),max(updated_at) FROM {table}"
            ).fetchone()) for table in ("threads", "nodes")]
    result = []
    for folder in ("threads", "nodes"):
        directory = workspace / folder
        if directory.is_symlink():
            raise OSError("unsafe_workspace_directory")
        for path in sorted(directory.glob("*.json")):
            if path.is_symlink():
                raise OSError("unsafe_workspace_document")
            info = path.stat()
            result.append((folder, path.name, info.st_size, info.st_mtime_ns))
    return result
