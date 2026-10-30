"""Best-effort activity projections never turn committed file work into failure."""
import hashlib
import json
import logging
from datetime import datetime, timezone

from threaddesk.core.errors import ThreadDeskError

_LOG = logging.getLogger(__name__)


def opened(store, receipt):
    from threaddesk.services.activity import ActivityService
    try:
        return ActivityService(store).record_open_receipt(receipt)
    except (ThreadDeskError, OSError, ValueError) as exc:
        _LOG.warning("File-open activity projection pending: %s", type(exc).__name__)
        return {"recorded": False, "status": "pending", "error": type(exc).__name__}


def changed(store, record, previous, source_info, source_key):
    return apply_change(store, change_evidence(record, previous, source_info, source_key))


def change_evidence(record, previous, source_info, source_key):
    """Persist this verified evidence before attempting its derived projection."""
    evidence = {"record": {"id": record["id"], "sha256": record["sha256"]},
                "previous_record": {"id": previous["id"], "sha256": previous["sha256"]},
                "source_modified_at": datetime.fromtimestamp(source_info.st_mtime, timezone.utc).isoformat()}
    # Identity binds the whole event, including both byte-version identities.
    # Restoring bytes/mtime or remapping an origin must not alias another event.
    identity = json.dumps({**evidence, "source_key": source_key, "mtime_ns": source_info.st_mtime_ns},
                          sort_keys=True, separators=(",", ":"))
    evidence["operation_id"] = "source:" + hashlib.sha256(identity.encode()).hexdigest()
    return evidence


def saved_change_evidence(source):
    """Read the durable version history, including pre-history receipts."""
    from threaddesk.services.library_import import LibraryImportError
    history = source.get("activity_evidence_history", [])
    if not isinstance(history, list):
        raise LibraryImportError("batch_receipt_damaged")
    latest = source.get("activity_evidence")
    events = {}
    for evidence in [*history, *([latest] if latest else [])]:
        if not isinstance(evidence, dict) or not isinstance(evidence.get("operation_id"), str):
            raise LibraryImportError("batch_receipt_damaged")
        identity = evidence["operation_id"]
        if identity in events and events[identity] != evidence:
            raise LibraryImportError("batch_receipt_damaged")
        events[identity] = evidence
    return list(events.values())


def apply_change(store, evidence):
    from threaddesk.services.activity import ActivityService
    try:
        return ActivityService(store).record_content_change(
            evidence["record"], evidence["previous_record"],
            source_modified_at=evidence["source_modified_at"], operation_id=evidence["operation_id"])
    except (ThreadDeskError, OSError, ValueError, OverflowError) as exc:
        _LOG.warning("File-change activity projection pending: %s", type(exc).__name__)
        return {"recorded": False, "status": "pending", "error": type(exc).__name__}
