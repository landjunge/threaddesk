"""Best-effort activity projections never turn committed file work into failure."""
from datetime import datetime, timezone
import logging

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
    return {"record": {"id": record["id"], "sha256": record["sha256"]},
            "previous_record": {"id": previous["id"], "sha256": previous["sha256"]},
            "source_modified_at": datetime.fromtimestamp(source_info.st_mtime, timezone.utc).isoformat(),
            "operation_id": "source:" + source_key + ":" + record["sha256"] + ":" + str(source_info.st_mtime_ns)}


def apply_change(store, evidence):
    from threaddesk.services.activity import ActivityService
    try:
        return ActivityService(store).record_content_change(
            evidence["record"], evidence["previous_record"],
            source_modified_at=evidence["source_modified_at"], operation_id=evidence["operation_id"])
    except (ThreadDeskError, OSError, ValueError, OverflowError) as exc:
        _LOG.warning("File-change activity projection pending: %s", type(exc).__name__)
        return {"recorded": False, "status": "pending", "error": type(exc).__name__}
