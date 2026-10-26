"""Refresh existing projections after canonical commits; never undo a saved action."""
from threaddesk.services.library_import import LibraryImporter
from threaddesk.services.library_index import LibraryIndex


def refresh_existing(store):
    importer = LibraryImporter(store)
    index = LibraryIndex(importer.root)
    if not index.path.exists():
        return {"status": "not_initialized"}
    try:
        # A failed post-commit refresh must not present old results as current.
        prior = index._read()
        if prior:
            index._replace({**prior, "status": "stale", "error": "canonical_change"})
        return index.rebuild(importer._read_records(), importer.blobs, store=store)
    except Exception as exc:
        # This is a post-commit projection boundary, not a second domain commit.
        return {"status": "stale", "error": type(exc).__name__}
