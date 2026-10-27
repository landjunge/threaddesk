"""Optional v2 lifecycle fields for metadata replicas, never deletion by absence."""
from __future__ import annotations

from copy import deepcopy

from threaddesk.services.trash import TrashService, _hash
from threaddesk.server_sync.store import SyncError

FORMAT = "threaddesk.metadata.v2"


def state(entry):
    return {key: entry[key] for key in ("generation", "revision", "state")}


def validate(value, document):
    if not isinstance(value, dict) or set(value) != {"thread", "nodes", "relations"}:
        raise SyncError("Invalid lifecycle metadata", "invalid_metadata")
    entries = [("thread", value["thread"])] if value["thread"] is not None else []
    for section in ("nodes", "relations"):
        if not isinstance(value[section], dict) or set(value[section]) - set(document[section]):
            raise SyncError("Lifecycle scope is outside its project", "metadata_scope", 409)
        entries.extend((section + "/" + key, item) for key, item in value[section].items())
    for _, item in entries:
        if (not isinstance(item, dict) or set(item) != {"generation", "revision", "state"}
                or type(item["generation"]) is not int or item["generation"] < 1
                or type(item["revision"]) is not int or item["revision"] < 1
                or item["state"] not in {"trashed", "restored", "purged"}):
            raise SyncError("Invalid lifecycle generation", "invalid_metadata")
    return deepcopy(value)


def export(store, thread_id, node_origins, relation_origins):
    result = {"thread": None, "nodes": {}, "relations": {}}
    entry = store.get_object_lifecycle("thread", thread_id)
    if entry is not None:
        result["thread"] = state(entry)
    for kind, origins in (("node", node_origins), ("relation", relation_origins)):
        for object_id, origin in origins.items():
            entry = store.get_object_lifecycle(kind, object_id)
            if entry is not None:
                result[kind + "s"][origin] = state(entry)
    return result if result["thread"] is not None or result["nodes"] or result["relations"] else None


def _states(document):
    data = document.get("lifecycle") or {}
    result = {"thread": data["thread"]} if data.get("thread") else {}
    for section in ("nodes", "relations"):
        result.update({section + "/" + key: item for key, item in data.get(section, {}).items()})
    return result


def _content(document, path):
    if path == "thread":
        # Deleting a thread hides its graph and whiteboard too, all of which
        # must still agree with the observed base before applying a tombstone.
        return {key: document[key] for key in ("thread", "nodes", "relations", "whiteboard")}
    section, origin = path.split("/", 1)
    return document[section].get(origin)


def guard_merge(base, incoming, current):
    """Return conflicts before applying any edits from a stale writer.

    A conservative full-document conflict keeps unrelated pending edits intact
    for review rather than partially committing an ambiguous delete/edit race.
    """
    b, left, right = map(_states, (base, incoming, current))
    conflicts = []
    for path in sorted(set(left) | set(right)):
        old, target, actual = b.get(path), left.get(path), right.get(path)
        reason = None
        if actual is not None and target is None:
            reason = "legacy_or_stale_lifecycle_writer"
        elif target == actual:
            if actual and actual["state"] in {"trashed", "purged"} and _content(incoming, path) != _content(current, path):
                reason = "edit_of_trashed_object"
        elif target is not None:
            if target["state"] == "purged":
                reason = "remote_purge_requires_local_review"
            elif actual is None:
                if target["generation"] != 1 or target["state"] != "trashed":
                    reason = "restore_without_matching_generation"
            elif target["generation"] < actual["generation"]:
                reason = "stale_generation"
            elif actual["state"] == "trashed" and target["state"] == "restored":
                if target["generation"] != actual["generation"] or target["revision"] != actual["revision"] + 1:
                    reason = "restore_without_matching_generation"
            elif actual["state"] == "restored" and target["state"] == "trashed":
                if target["generation"] != actual["generation"] + 1 or target["revision"] != 1:
                    reason = "generation_gap"
            else:
                reason = "lifecycle_conflict"
            if reason is None and _content(base, path) != _content(current, path):
                reason = "concurrent_delete_edit"
        if reason:
            conflicts.append({"path": "lifecycle/" + path, "base": old, "incoming": target,
                              "current": actual, "reason": reason})
    return conflicts


def conflict_value(document, path):
    return {"lifecycle": _states(document).get(path.removeprefix("lifecycle/")),
            "document_digest": _hash(document)}


def conflict_view(core, thread_id):
    """Stable readback values; repeated reads never mint changing page IDs."""
    from threaddesk.server_sync.metadata import export_document, list_conflicts
    conflicts = list_conflicts(core, thread_id)
    if not conflicts:
        return []
    document = export_document(core, thread_id)
    result = []
    for conflict in conflicts:
        if conflict["path"].startswith("lifecycle/"):
            current = conflict_value(document, conflict["path"])
        else:
            current = document
            for part in conflict["path"].split("/"):
                current = current.get(part, {"$missing": True}) if isinstance(current, dict) else {"$missing": True}
        operation_id = "resolve_" + _hash([conflict["id"], current])
        result.append({**conflict, "expected_current": current, "operation_id": operation_id})
    return result


def resolve_document(document, path, chosen_value):
    actual = _states(document).get(path.removeprefix("lifecycle/"))
    if chosen_value == actual:
        return deepcopy(document)
    if chosen_value is None or chosen_value.get("state") == "purged":
        raise SyncError("Keep lifecycle history; use an explicit matching restore or local purge", "metadata_lifecycle_conflict", 409)
    target = deepcopy(document)
    target.setdefault("lifecycle", {"thread": None, "nodes": {}, "relations": {}})
    target["format"] = FORMAT
    inner = path.removeprefix("lifecycle/")
    if inner == "thread":
        target["lifecycle"]["thread"] = deepcopy(chosen_value)
    else:
        section, origin = inner.split("/", 1)
        target["lifecycle"][section][origin] = deepcopy(chosen_value)
    conflicts = guard_merge(document, target, document)
    # Explicitly adopting one previously refused delete/restore generation is
    # safe when the caller binds the entire current document digest. The same
    # transition is never inferred during automatic synchronization.
    can_adopt = (chosen_value["state"] == "restored" and chosen_value["revision"] == 2
                 and chosen_value["generation"] == ((actual["generation"] if actual else 0) + 1)
                 and (actual is None or actual["state"] == "restored"))
    if conflicts and not can_adopt:
        raise SyncError("Lifecycle generation cannot be adopted", "metadata_lifecycle_conflict", 409)
    return target


def apply(core, thread_id, document, *, phase, explicit_resolution=False):
    """Reuse TrashService mutation bodies inside metadata's existing transaction."""
    service = TrashService(core.store)
    desired = _states(document)
    namespace = None
    for path, target in sorted(desired.items(), key=lambda item: item[0] == "thread" if phase == "after" else item[0] != "thread"):
        if path == "thread":
            kind, object_id = "thread", thread_id
        else:
            section, origin = path.split("/", 1)
            kind = "node" if section == "nodes" else "relation"
            items = (core.store.list_nodes(include_trashed=True) if kind == "node"
                     else core.store.list_relations(include_trashed=True))
            # Native origin suffixes only bind local objects from this exported
            # namespace; the existing sync-origin binding wins for replicas.
            if namespace is None:
                from threaddesk.server_sync.metadata import _namespace
                namespace = _namespace(core)
            obj = next((item for item in items if (item.metadata.get("sync_origin") or namespace + ":" + item.id) == origin), None)
            if obj is None:
                raise SyncError("Lifecycle original is missing", "metadata_lifecycle_conflict", 409)
            object_id = obj.id
        current = core.store.get_object_lifecycle(kind, object_id)
        if current and state(current) == target:
            continue
        if phase == "before" and target["state"] == "restored" and current and current["state"] == "trashed":
            service._restore_in_transaction(trash_id=current["trash_id"], generation=target["generation"],
                                            expected_revision=current["revision"])
        elif phase == "before" and target["state"] == "restored" and (current is None or current["state"] == "restored"):
            if (not explicit_resolution or target["generation"] != ((current["generation"] if current else 0) + 1)
                    or target["revision"] != 2):
                raise SyncError("Restore requires matching generation", "metadata_lifecycle_conflict", 409)
            obj = service._object(kind, object_id)
            moved = service._move_in_transaction(kind=kind, object_id=object_id,
                expected_revision=obj["revision"], actor="metadata_conflict_resolution")["entry"]
            service._restore_in_transaction(trash_id=moved["trash_id"], generation=moved["generation"],
                                            expected_revision=moved["revision"])
        elif phase == "after" and target["state"] == "trashed":
            obj = service._object(kind, object_id)
            result = service._move_in_transaction(kind=kind, object_id=object_id,
                       expected_revision=obj["revision"], actor="authenticated_metadata_peer")
            if state(result["entry"]) != target:
                raise SyncError("Lifecycle generation changed", "metadata_lifecycle_conflict", 409)
