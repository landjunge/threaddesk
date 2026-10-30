"""Revision- and operation-bound graph views; no renderer owns domain state."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re

from threaddesk.core.errors import ManagementError
from threaddesk.core.models import now_iso
from threaddesk.services.graph_read import validate_filters
from threaddesk.services.graph_state import GraphDocument

ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}\Z")


def _initial():
    return {"schema_version": 1, "generation": 0, "views": {}, "operations": {}}


def _identity(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ManagementError("validation_error", "A bounded graph view identity is required.")
    return value


def validate_state(value):
    if not isinstance(value, dict) or set(value) - {"camera", "positions", "filters", "selection"}:
        raise ManagementError("validation_error", "Unknown graph view field.")
    state = {"camera": {"x": 0, "y": 0, "scale": 1}, "positions": {}, "filters": {}, "selection": [], **copy.deepcopy(value)}
    camera = state["camera"]
    if not isinstance(camera, dict) or set(camera) != {"x", "y", "scale"}:
        raise ManagementError("validation_error", "Graph camera needs x, y and scale.")
    for name, number in camera.items():
        if type(number) not in {int, float} or not math.isfinite(number) or abs(number) > 1e8:
            raise ManagementError("validation_error", "Invalid graph camera coordinate.")
    if not .04 <= camera["scale"] <= 4:
        raise ManagementError("validation_error", "Invalid graph camera scale.")
    positions = state["positions"]
    if not isinstance(positions, dict) or len(positions) > 10000:
        raise ManagementError("validation_error", "At most 10000 positions are allowed.")
    for identity, point in positions.items():
        _identity(identity)
        if not isinstance(point, dict) or set(point) - {"x", "y", "fixed"} or not {"x", "y"} <= set(point):
            raise ManagementError("validation_error", "Invalid graph node position.")
        for axis in ("x", "y"):
            if type(point[axis]) not in {int, float} or not math.isfinite(point[axis]) or abs(point[axis]) > 1e8:
                raise ManagementError("validation_error", "Invalid graph node coordinate.")
        if "fixed" in point and type(point["fixed"]) is not bool:
            raise ManagementError("validation_error", "Invalid graph fixed state.")
    filters = validate_filters(state["filters"])
    for name in ("as_of", "limit", "offset"):
        filters.pop(name, None)
    state["filters"] = filters
    if not isinstance(state["selection"], list) or len(state["selection"]) > 100:
        raise ManagementError("validation_error", "At most 100 graph selections are allowed.")
    state["selection"] = list(dict.fromkeys(_identity(identity) for identity in state["selection"]))
    return state


def _request(arguments):
    if (not isinstance(arguments, dict) or set(arguments) - {"action", "id", "operation_id", "expected_revision", "data"}
            or not {"action", "id", "operation_id", "expected_revision"} <= set(arguments)):
        raise ManagementError("validation_error", "Invalid graph view request.")
    args = copy.deepcopy(arguments)
    action = args["action"]
    if not isinstance(action, str) or action not in {"save", "delete"}:
        raise ManagementError("validation_error", "Unknown graph view action.")
    identity, operation_id = _identity(args["id"]), _identity(args["operation_id"])
    if type(args["expected_revision"]) is not int or args["expected_revision"] < 0:
        raise ManagementError("validation_error", "A nonnegative expected revision is required.")
    data = args.get("data", {})
    if not isinstance(data, dict) or set(data) - {"title", "state"} or action == "delete" and data:
        raise ManagementError("validation_error", "Invalid graph view data.")
    if action == "save":
        title = data.get("title")
        if not isinstance(title, str) or not title.strip() or len(title) > 160:
            raise ManagementError("validation_error", "A graph view title is required.")
        view_state = validate_state(data.get("state", {}))
    # Hash the actual request, not expanded defaults or the current time.
    digest = hashlib.sha256(json.dumps(args, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    return args, digest, action, identity, operation_id, title if action == "save" else None, view_state if action == "save" else None


class GraphViewService:
    def __init__(self, store):
        self.document = GraphDocument(store, "graph-views.json", _initial)

    def _read(self):
        data = self.document.read()
        if (type(data.get("generation")) is not int or not isinstance(data.get("views"), dict)
                or not isinstance(data.get("operations"), dict)):
            raise ManagementError("graph_state_unavailable", "Graph view state is invalid.")
        return data

    def list(self, *, limit=100, offset=0):
        if type(limit) is not int or not 1 <= limit <= 200 or type(offset) is not int or offset < 0:
            raise ManagementError("validation_error", "Invalid graph view page.")
        data = self._read()
        rows = [{key: row[key] for key in ("id", "title", "revision", "updated_at")}
                for row in data["views"].values() if not row.get("deleted")]
        rows.sort(key=lambda row: (row["title"].casefold(), row["id"]))
        end = offset + limit
        return {"schema": "threaddesk.graph-views.v1", "generation": data["generation"],
                "views": rows[offset:end], "total": len(rows), "next_offset": end if end < len(rows) else None}

    def get(self, identity):
        row = self._read()["views"].get(_identity(identity))
        if not row or row.get("deleted"):
            raise ManagementError("not_found", "Graph view was not found.")
        return copy.deepcopy(row)

    def operation_status(self, operation_id):
        saved = self._read()["operations"].get(_identity(operation_id))
        return {"operation_id": operation_id, "found": saved is not None,
                "result": copy.deepcopy(saved["result"]) if saved else None}

    def verify_recorded_request(self, arguments):
        """Read-only digest validation when an outer command receipt was lost."""
        _args, digest, _action, _identity, operation_id, _title, _state = _request(arguments)
        saved = self._read()["operations"].get(operation_id)
        if saved and saved["digest"] != digest:
            raise ManagementError("operation_conflict", "Operation has a different graph view payload.")
        return {"found": saved is not None,
                "result": {**copy.deepcopy(saved["result"]), "duplicate": True} if saved else None}

    def manage(self, arguments):
        args, digest, action, identity, operation_id, title, view_state = _request(arguments)
        with self.document.locked():
            owner = self._read()
            old = owner["operations"].get(operation_id)
            if old:
                if old["digest"] != digest:
                    raise ManagementError("operation_conflict", "Operation has a different graph view payload.")
                return {**copy.deepcopy(old["result"]), "duplicate": True}
            previous = owner["views"].get(identity)
            revision = previous["revision"] if previous else 0
            if revision != args["expected_revision"]:
                raise ManagementError("revision_conflict", "Graph view has changed.", actual_revision=revision,
                                      expected_revision=args["expected_revision"])
            if action == "delete" and (not previous or previous.get("deleted")):
                raise ManagementError("not_found", "Graph view was not found.")
            if (not previous and len(owner["views"]) >= 200) or len(owner["operations"]) >= 10000:
                raise ManagementError("graph_view_limit", "Graph view budget was reached.")
            stamp = now_iso()
            row = {"id": identity, "revision": revision + 1, "updated_at": stamp,
                   "title": title.strip() if action == "save" else previous["title"],
                   "state": view_state if action == "save" else {}, "deleted": action == "delete"}
            owner["views"][identity] = row
            owner["generation"] += 1
            receipt_view = {key: row[key] for key in ("id", "title", "revision", "updated_at", "deleted")}
            result = {"operation_id": operation_id, "action": action, "view": receipt_view,
                      "generation": owner["generation"], "duplicate": False}
            owner["operations"][operation_id] = {"digest": digest, "result": result}
            self.document.write(owner)
            return copy.deepcopy(result)
