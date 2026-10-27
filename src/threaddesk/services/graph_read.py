"""Versioned, inert graph projection with bounded filters and file evidence."""
from __future__ import annotations

import copy

from threaddesk.core.errors import ManagementError, ThreadDeskError
from threaddesk.core.models import NODE_KINDS, NODE_STATUSES, now_iso
from threaddesk.services.activity import ActivityService, BANDS, MODES, utc
from threaddesk.services.library_import import LibraryImporter
from threaddesk.services.library_search.normalize import folded as normalize
from threaddesk.services.library_search.projects import project_records

FILTER_FIELDS = {"query", "kind", "status", "project_id", "mode", "band", "center", "hops", "as_of", "limit", "offset", "node_ids"}


def validate_filters(arguments):
    if not isinstance(arguments, dict) or set(arguments) - FILTER_FIELDS:
        raise ManagementError("validation_error", "Unknown graph filter.")
    value = {"query": "", "kind": "", "status": "", "project_id": "", "mode": "status",
             "band": "", "center": "", "hops": 0, "limit": 1000, "offset": 0, **arguments}
    for name in ("query", "kind", "status", "project_id", "band", "center"):
        if not isinstance(value[name], str) or len(value[name]) > (200 if name == "query" else 100):
            raise ManagementError("validation_error", "Invalid graph filter text.")
    if not isinstance(value["mode"], str) or value["mode"] not in MODES or value["band"] not in {"", *BANDS}:
        raise ManagementError("validation_error", "Unknown graph activity mode or age interval.")
    if ((value["kind"] and value["kind"] not in NODE_KINDS)
            or (value["status"] and value["status"] not in NODE_STATUSES)):
        raise ManagementError("validation_error", "Unknown graph node kind or status.")
    if type(value["hops"]) is not int or not 0 <= value["hops"] <= 2:
        raise ManagementError("validation_error", "A neighborhood has at most two steps.")
    if (type(value["limit"]) is not int or not 1 <= value["limit"] <= 1000
            or type(value["offset"]) is not int or value["offset"] < 0):
        raise ManagementError("validation_error", "Invalid graph page.")
    if "node_ids" in value and (not isinstance(value["node_ids"], list) or not 1 <= len(value["node_ids"]) <= 1000
                                or any(not isinstance(identity, str) or not identity or len(identity) > 100 for identity in value["node_ids"])):
        raise ManagementError("validation_error", "At most 1000 exact graph identities are allowed.")
    value["as_of"] = utc(value.get("as_of") or now_iso()).isoformat()
    return value


class GraphReadService:
    def __init__(self, store):
        self.store = store

    def change_status(self, *, workspace_id):
        from threaddesk.services.graph_changes import GraphChangeService
        return GraphChangeService(self.store).status(workspace_id=workspace_id)

    def query(self, base_graph, **arguments):
        from threaddesk.services.commands.model import workspace_identity
        filters = validate_filters(arguments)
        nodes = copy.deepcopy(base_graph["nodes"])
        relations = copy.deepcopy(base_graph["relations"])
        by_id = {node["id"]: node for node in nodes}
        records = list(project_records(self.store, LibraryImporter(self.store)._read_records()))
        project_members = set()
        project = filters["project_id"]
        for record in records:
            targets = [node["id"] for node in nodes
                       if record.get("thread_id") and node.get("metadata", {}).get("thread_id") == record["thread_id"]
                       and node["kind"] == "project"]
            record["activity_node_ids"] = list(set(targets + list(record.get("project_ids") or [])))
        if project:
            project_members.add(project)
            thread_id = by_id.get(project, {}).get("metadata", {}).get("thread_id")
            project_members.update(node["id"] for node in nodes if
                                   node.get("metadata", {}).get("project_id") == project or
                                   project in (node.get("metadata", {}).get("project_ids") or []) or
                                   thread_id and node.get("metadata", {}).get("thread_id") == thread_id)
            changed = True
            while changed:
                before = len(project_members)
                project_members.update(edge["target_id"] for edge in relations
                                       if edge["kind"] == "contains" and edge["source_id"] in project_members)
                changed = len(project_members) != before
        activity_status, activity_error = "ready", None
        try:
            activity = ActivityService(self.store).node_activities(
                records, set(by_id), as_of=filters["as_of"], mode=filters["mode"])
        except (ThreadDeskError, OSError, ValueError, TypeError, KeyError) as exc:
            # Activity is an independent projection: keep navigation available,
            # preserve the damaged evidence and declare its unavailable status.
            activity_status, activity_error = "unavailable", getattr(exc, "code", type(exc).__name__)
            activity = {"revision": None, "nodes": {identity: {
                "file_modified_at": None, "file_accessed_at": None, "modified": None,
                "accessed": None, "selected": None, "band": "unknown", "age_seconds": None,
                "clock_warning": None} for identity in by_id}}
        neighborhood = None
        if filters["center"]:
            neighborhood = {filters["center"]} if filters["center"] in by_id else set()
            for _ in range(filters["hops"]):
                reached = set(neighborhood)
                for edge in relations:
                    if edge["source_id"] in neighborhood:
                        reached.add(edge["target_id"])
                    if edge["target_id"] in neighborhood:
                        reached.add(edge["source_id"])
                neighborhood = reached
        query = normalize(filters["query"])
        requested = set(filters["node_ids"]) if "node_ids" in filters else None
        visible = []
        for node in nodes:
            node["activity"] = activity["nodes"][node["id"]]
            if ((not query or query in normalize(node["title"] + " " + (node.get("details") or "")))
                    and (not filters["kind"] or node["kind"] == filters["kind"])
                    and (not filters["status"] or node["status"] == filters["status"])
                    and (not project or node["id"] in project_members)
                    and (neighborhood is None or node["id"] in neighborhood)
                    and (requested is None or node["id"] in requested)
                    and (not filters["band"] or node["activity"]["band"] == filters["band"])):
                visible.append(node)
        visible.sort(key=lambda node: (node["title"].casefold(), node["id"]))
        start, end = filters["offset"], filters["offset"] + filters["limit"]
        page = visible[start:end]
        ids = {node["id"] for node in page}
        edges = [edge for edge in relations if edge["source_id"] in ids and edge["target_id"] in ids]
        return {"schema": "threaddesk.graph.v2", "workspace_id": workspace_identity(self.store), "as_of": filters["as_of"],
                "activity_revision": activity["revision"], "filters": filters,
                "activity_status": activity_status, "activity_error": activity_error,
                "nodes": page, "relations": edges[:10000],
                "counts": {"nodes": len(page), "relations": min(10000, len(edges))},
                "total": len(visible), "returned": len(page),
                "next_offset": end if end < len(visible) else None,
                "relations_truncated": len(edges) > 10000,
                "bands": list(BANDS), "activity_scope": "visible_attached_files_only"}
