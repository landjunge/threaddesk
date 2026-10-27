"""The explicit, preview-bound exception to immutable operation payloads.

Requests and execution evidence remain unchanged. Only an exact result copy
may be reduced during its owner's confirmed purge transaction.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json

from threaddesk.core.errors import ManagementError


SCHEMA = "threaddesk.purge-receipt-reduction.v1"


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def reduced_record(store, record, *, expected_record_digest, reduced_result, evidence):
    if not store.in_transaction:
        raise ManagementError("purge_transaction_required", "Belegreduktion benötigt den besitzenden Writer.")
    if record is None or digest(record) != expected_record_digest:
        raise ManagementError("receipt_conflict", "Operationsbeleg hat sich seit der Vorschau geändert.")
    fields = {"schema", "kind", "object_id", "trash_id", "generation", "purge_operation_id",
              "purged_at", "original_record_digest", "original_result_digest", "result_digest", "paths"}
    if (not isinstance(evidence, dict) or set(evidence) != fields or evidence.get("schema") != SCHEMA
            or evidence["original_record_digest"] != expected_record_digest
            or evidence["original_result_digest"] != digest(record.get("result"))
            or evidence["result_digest"] != digest(reduced_result)
            or evidence["kind"] not in {"thread", "node", "relation"}
            or not isinstance(evidence["paths"], list) or not evidence["paths"]
            or not isinstance(record.get("request_hash"), str)):
        raise ManagementError("invalid_receipt_reduction", "Exakter versionierter Reduktionsbeleg fehlt.")
    result = deepcopy(record)
    result["result"] = deepcopy(reduced_result)
    result["purge_reductions"] = [*result.get("purge_reductions", []), deepcopy(evidence)]
    return result
