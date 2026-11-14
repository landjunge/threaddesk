"""Content-free projection shared by the existing whiteboard stores.

Arbitrary metadata can itself contain full contributions (merge conflicts and
agent reports). Only known correlation/correction references cross this boundary.
"""
from threaddesk.core.models import WhiteboardEntry

REFERENCE_PATHS = (
    ('return_id',), ('job_id',), ('event_id',), ('handoff_revision',),
    ('supersedes_entry_id',),
    ('whiteboard_edit', 'entry_id'), ('whiteboard_edit', 'previous_entry_id'),
)


def metadata_row(data, *, sql_reference_pairs=False):
    # Keep legacy model defaults, including a missing hash remaining None.
    row = WhiteboardEntry.from_dict({**data, 'content': '', 'metadata': {}}).to_dict()
    del row['content']
    source = data.get('metadata') or {}
    for path in REFERENCE_PATHS:
        value = source
        for key in path:
            value = value.get(key) if isinstance(value, dict) else None
        if sql_reference_pairs:
            value = value[0]
        if value is None or not isinstance(value, (str, int, float, bool)):
            continue
        target = row['metadata']
        for key in path[:-1]:
            target = target.setdefault(key, {})
        target[path[-1]] = value
    return row


def page_result(items, total, *, offset, limit):
    end = offset + limit
    return {'items': items, 'total': total,
            'next_offset': end if end < total else None}


def metadata_sql():
    """Project in SQLite: never return content or arbitrary metadata to Python."""
    # Two paths make json_extract return JSON text instead of SQL scalars.
    # This preserves booleans and integers beyond SQLite's signed 64-bit range.
    # metadata_row unwraps the first of each pair after Python JSON decoding.
    # Remove freeform metadata, then restore only the known reference paths.
    values = ', '.join(
        f"'$.metadata.{'.'.join(path)}', json_extract(payload, '$.metadata.{'.'.join(path)}', '$.metadata.{'.'.join(path)}')"
        for path in REFERENCE_PATHS)
    return f"json_set(json_remove(payload, '$.content', '$.metadata'), {values})"
