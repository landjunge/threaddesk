"""Label source snapshots without deleting old records or breaking their IDs."""
import json
from pathlib import Path


def annotate_versions(records, library_root):
    from threaddesk.services.library_files.state import check_path, fail
    path = Path(library_root).parent / "library-batch-sources.json"
    check_path(path)
    if not path.exists():
        return [{**row, "current_version": True} for row in records]
    if path.stat().st_size > 16 * 1024 * 1024:
        fail("file_state_limit", "Source receipts exceed the size limit")
    try:
        source = json.loads(path.read_text())["sources"]
        current = {row.get("record_id") for row in source.values() if isinstance(row, dict)}
        historical = {identity for row in source.values() if isinstance(row, dict)
                      for identity in row.get("history", []) if isinstance(identity, str)}
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ValueError("source_receipts_unreadable") from exc
    return [{**row, "current_version": bool(row.get("copied_from"))
             or row["id"] in current or row["id"] not in historical} for row in records]
