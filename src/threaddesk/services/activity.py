"""Evidence-bound file activity; technical reads and import time are not work."""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json

from threaddesk.core.errors import ManagementError
from threaddesk.core.models import now_iso
from threaddesk.services.graph_state import GraphDocument

MODES = {"status", "modified", "accessed", "work"}
BANDS = ("24h", "7d", "30d", "90d", "older", "unknown")
LIMITS = ((86400, "24h"), (7 * 86400, "7d"), (30 * 86400, "30d"), (90 * 86400, "90d"))


def utc(value):
    """Require an explicit offset; locale and DST never affect elapsed age."""
    if not isinstance(value, str) or len(value) > 64:
        raise ManagementError("validation_error", "An offset-qualified timestamp is required.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("Timezone required")
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError) as exc:
        raise ManagementError("validation_error", "An offset-qualified timestamp is required.") from exc


def activity_band(occurred_at, as_of):
    if not occurred_at:
        return {"band": "unknown", "age_seconds": None, "clock_warning": None}
    age = (utc(as_of) - utc(occurred_at)).total_seconds()
    if age < 0:
        return {"band": "unknown", "age_seconds": age, "clock_warning": "future_timestamp"}
    band = next((name for threshold, name in LIMITS if age <= threshold), "older")
    return {"band": band, "age_seconds": age, "clock_warning": None}


def _initial():
    return {"schema_version": 1, "revision": 0, "files": {}, "operations": {}}


class ActivityService:
    """Internal completion hooks, with a separate inert public read interface.

    Neither callers nor a Graph query can submit an invented actor identity.
    Sources name the actual domain completion that supplied the evidence.
    """
    def __init__(self, store):
        self.store = store
        self.document = GraphDocument(store, "file-activity.json", _initial)

    def _read(self):
        data = self.document.read()
        if (type(data.get("revision")) is not int or data["revision"] < 0
                or not isinstance(data.get("files"), dict)
                or not isinstance(data.get("operations"), dict)):
            raise ManagementError("graph_state_unavailable", "File activity state is invalid.")
        return data

    @staticmethod
    def _apply(data, event):
        encoded = json.dumps(event, sort_keys=True, ensure_ascii=False, allow_nan=False)
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        identity = event["event_id"]
        old = data["operations"].get(identity)
        if old:
            if old["digest"] != digest:
                raise ManagementError("operation_conflict", "Activity operation has a different payload.")
            return {"recorded": True, "duplicate": True, "revision": old["revision"]}
        if len(data["operations"]) >= 20000:
            raise ManagementError("activity_limit", "File activity history has reached its budget.")
        events = data["files"].get(event["record_id"], {})
        previous = events.get(event["channel"])
        newer = not previous or utc(event["occurred_at"]) >= utc(previous["occurred_at"])
        data["revision"] += 1
        if newer:
            data["files"].setdefault(event["record_id"], {})[event["channel"]] = event
        data["operations"][identity] = {"digest": digest, "revision": data["revision"]}
        return {"recorded": True, "duplicate": False, "revision": data["revision"]}

    def _record(self, event):
        with self.document.locked():
            data = self._read()
            result = self._apply(data, event)
            if not result["duplicate"]:
                self.document.write(data)
            return result

    @staticmethod
    def _open_event(receipt):
        if receipt.get("action") != "open" or receipt.get("status") != "launch_requested":
            return None
        return {"event_id": "file-open:" + receipt["operation_id"],
                "record_id": receipt["record_id"], "channel": "accessed",
                "kind": "open_requested", "source": "library_open_receipt",
                "occurred_at": utc(receipt["launch_requested_at"]).isoformat(), "sha256": receipt["sha256"],
                "human_read_confirmed": False}

    @staticmethod
    def _change_event(record, previous_record, *, source_modified_at, operation_id):
        if (not previous_record or record.get("sha256") == previous_record.get("sha256")
                or not record.get("sha256") or not previous_record.get("sha256") or not source_modified_at):
            return None
        return {"event_id": "file-change:" + operation_id,
                "record_id": record["id"], "channel": "modified",
                "kind": "content_change_observed", "source": "verified_source_refresh",
                "occurred_at": utc(source_modified_at).isoformat(), "sha256": record["sha256"],
                "previous_sha256": previous_record["sha256"], "previous_record_id": previous_record["id"]}

    def record_open_receipt(self, receipt):
        event = self._open_event(receipt)
        return self._record(event) if event else {"recorded": False, "reason": "no_confirmed_launch_request"}

    def record_content_change(self, record, previous_record, *, source_modified_at, operation_id):
        event = self._change_event(record, previous_record, source_modified_at=source_modified_at, operation_id=operation_id)
        return self._record(event) if event else {"recorded": False, "reason": "no_confirmed_content_change"}

    def files(self, record_ids, *, as_of=None):
        if (not isinstance(record_ids, (list, tuple, set)) or len(record_ids) > 10000
                or any(not isinstance(identity, str) or not identity or len(identity) > 100 for identity in record_ids)):
            raise ManagementError("validation_error", "At most 10000 file identities are allowed.")
        stamp = utc(as_of or now_iso()).isoformat()
        data = self._read()
        return {"schema": "threaddesk.file-activity.v1", "as_of": stamp,
                "revision": data["revision"], "files": {
                    identity: copy.deepcopy(data["files"].get(identity, {})) for identity in record_ids}}

    def reconcile(self, *, limit=50, offset=0):
        """Retry bounded committed evidence, never launch or restat a source.

        The caller follows next_offset and starts another pass when new receipts
        arrive. Per-evidence failure is reported without blocking other records.
        Ordinary activity/graph reads never call this write-side operation.
        """
        from pathlib import Path
        from threaddesk.services.library_files.state import read_state
        from threaddesk.services.library_batch.jobs import JobStore
        if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or offset < 0:
            raise ManagementError("validation_error", "Invalid activity reconciliation page.")
        files = read_state(Path(self.store.workspace_path) / "library-files")
        sources = JobStore(self.store).read("library-batch-sources.json", {"sources": {}})
        candidates = {}
        for operation in files["operations"].values():
            receipt = operation.get("result", {})
            if receipt.get("action") == "open" and receipt.get("status") == "launch_requested":
                candidates["file-open:" + receipt["operation_id"]] = ("accessed", receipt)
        for source in sources.get("sources", {}).values():
            evidence = source.get("activity_evidence")
            if evidence:
                candidates["file-change:" + evidence["operation_id"]] = ("modified", evidence)
        keys = sorted(candidates)
        recorded = duplicates = failed = 0
        errors = []
        page = keys[offset:offset + limit]
        if page:
            with self.document.locked():
                data = self._read()
                for identity in page:
                    channel, evidence = candidates[identity]
                    try:
                        event = (self._open_event(evidence) if channel == "accessed" else
                                 self._change_event(evidence["record"], evidence["previous_record"],
                                                    source_modified_at=evidence["source_modified_at"],
                                                    operation_id=evidence["operation_id"]))
                        if event is None:
                            continue
                        result = self._apply(data, event)
                        if result["duplicate"]:
                            duplicates += 1
                        else:
                            recorded += 1
                    except (ManagementError, OSError, ValueError, KeyError, TypeError) as exc:
                        failed += 1
                        if len(errors) < 10:
                            errors.append({"event_id": identity, "code": getattr(exc, "code", type(exc).__name__)})
                if recorded:
                    self.document.write(data)
        end = offset + limit
        return {"status": "partial" if failed else "ready", "total": len(keys),
                "processed": len(keys[offset:end]), "recorded": recorded, "duplicates": duplicates,
                "failed": failed, "next_offset": end if end < len(keys) else None,
                "errors": errors, "errors_truncated": failed > len(errors)}

    def node_activities(self, records, node_ids, *, as_of=None, mode="work"):
        if mode not in MODES:
            raise ManagementError("validation_error", "Unknown activity mode.")
        stamp = utc(as_of or now_iso()).isoformat()
        data = self._read()
        result = {identity: {"file_modified_at": None, "file_accessed_at": None,
                             "modified": None, "accessed": None} for identity in node_ids}
        for record in records:
            if record.get("trashed") or record.get("status") != "stored":
                continue
            targets = {record["id"], *(record.get("node_ids") or [])}
            if record.get("node_id"):
                targets.add(record["node_id"])
            targets.update(record.get("activity_node_ids") or [])
            events = data["files"].get(record["id"], {})
            for target in targets.intersection(result):
                for channel in ("modified", "accessed"):
                    event = events.get(channel)
                    previous = result[target][channel]
                    if event and (not previous or utc(event["occurred_at"]) > utc(previous["occurred_at"])):
                        result[target][channel] = {**copy.deepcopy(event), "filename": record.get("filename", ""),
                                                   "aggregation": "direct" if target == record["id"] else "attached_file"}
                        result[target]["file_" + channel + "_at"] = event["occurred_at"]
        for value in result.values():
            selected = ([value.get(mode)] if mode in {"modified", "accessed"}
                        else [value["modified"], value["accessed"]])
            selected = [event for event in selected if event]
            event = max(selected, key=lambda item: utc(item["occurred_at"])) if selected else None
            value.update(selected=event, **activity_band(event["occurred_at"] if event else None, stamp))
        return {"as_of": stamp, "revision": data["revision"], "nodes": result}
