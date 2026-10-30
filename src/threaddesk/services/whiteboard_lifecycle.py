"""Whiteboards are views of the existing thread log, never a second store.

A board has its thread's identity and title. Corrections append an event; saved
entries, return bindings and room contributions remain unchanged. The explicit
open/closed state is persisted in ThreadContext.extra, not a window-visibility
claim. Thread trash owns reversible removal and the existing purge contract.
"""
from __future__ import annotations

from dataclasses import replace

from threaddesk.core.errors import ManagementError, NotFound
from threaddesk.core.models import KnowledgeNode, Relation, now_iso

KEY = "whiteboard"
PREFIX = "wb-"


def state(thread):
    value = thread.context.extra.get(KEY)
    return "closed" if isinstance(value, dict) and value.get("state") == "closed" else "open"


def require_writable(thread):
    if thread.status == "archived" or state(thread) == "closed":
        raise ManagementError("whiteboard_closed", "Whiteboard zuerst wiederherstellen beziehungsweise öffnen.")


def effective_entries(entries):
    """Project corrections while retaining the immutable originals separately."""
    by_id = {entry.id: entry for entry in entries}
    corrected = {}
    corrections = set()
    for entry in sorted(entries, key=lambda row: (row.ordinal, row.created_at, row.id)):
        marker = entry.metadata.get("whiteboard_edit")
        if (not isinstance(marker, dict) or not isinstance(marker.get("entry_id"), str)
                or not isinstance(marker.get("previous_entry_id"), str)):
            continue
        original = by_id.get(marker.get("entry_id"))
        if original is None or original.id == entry.id:
            continue
        previous = corrected.get(original.id, original)
        if marker.get("previous_entry_id") != previous.id:
            continue
        corrected[original.id] = entry
        corrections.add(entry.id)
    result = []
    for entry in entries:
        if entry.id in corrections:
            continue
        change = corrected.get(entry.id)
        clean = {key: value for key, value in entry.metadata.items() if key != "whiteboard_edited"}
        if change is None:
            result.append(replace(entry, metadata=clean) if "whiteboard_edited" in entry.metadata else entry)
        else:
            result.append(replace(entry, content=change.content, metadata={**clean,
                "whiteboard_edited": {"correction_id": change.id, "updated_at": change.created_at,
                                      "actor": change.actor, "original_content": entry.content}}))
    return result


class WhiteboardService:
    def __init__(self, service):
        self.service, self.store = service, service.store

    def get(self, identity):
        thread = self.store.get_thread(identity)
        entries = self.store.list_whiteboard(identity)
        return {"schema": "threaddesk.whiteboard.v1", "id": identity,
                "thread_id": identity, "graph_node_id": PREFIX + identity,
                "title": thread.title, "state": state(thread),
                "status": "archived" if thread.status == "archived" else state(thread),
                "revision": thread.revision, "updated_at": thread.updated_at,
                "entry_count": len(entries), "ui_path": "/?thread=" + identity + "#notes",
                "lifecycle_scope": "owning_thread", "visibility_evidence": "saved_state_only"}

    def list(self, *, include_archived=False):
        return [self.get(thread.id) for thread in self.store.list_threads(include_archived=include_archived)
                if self.exists(thread)]

    def exists(self, thread):
        return KEY in thread.context.extra or bool(self.store.list_whiteboard(thread.id))

    def _save_state(self, thread, opened):
        thread.context.extra = {**thread.context.extra, KEY: {"version": 1, "state": "open" if opened else "closed"}}
        thread.updated_at = now_iso()
        self.store.save_thread(thread)
        self.service.bus.emit("whiteboard.state_changed", {"thread_id": thread.id,
                              "state": state(thread), "revision": thread.revision})
        return {"thread": thread.to_dict()}

    def create(self, title, description=""):
        thread = self.service.create(title, description)
        return self._save_state(thread, True)

    def open(self, identity):
        thread = self.store.get_thread(identity)
        if thread.status == "archived":
            raise ManagementError("whiteboard_archived", "Whiteboard zuerst aus dem Archiv wiederherstellen.")
        self.service.switch(identity)
        return self._save_state(thread, True)

    def close(self, identity):
        return self._save_state(self.store.get_thread(identity), False)

    def rename(self, identity, title):
        return {"thread": self.service.rename(identity, title).to_dict()}

    def archive(self, identity):
        return {"thread": self.service.archive(identity).to_dict()}

    def unarchive(self, identity):
        return {"thread": self.service.unarchive(identity).to_dict()}

    def edit(self, identity, *, entry_id, content, actor="human", actor_type="human", actor_id=None):
        thread = self.store.get_thread(identity)
        require_writable(thread)
        entries = self.store.list_whiteboard(identity)
        original = next((row for row in entries if row.id == entry_id), None)
        if original is None:
            raise NotFound("Whiteboard-Beitrag wurde nicht gefunden.")
        current = next((row for row in effective_entries(entries) if row.id == entry_id), None)
        if current is None:
            raise ManagementError("validation_error", "Den ursprünglichen Beitrag bearbeiten, nicht dessen Korrekturereignis.")
        previous = current.metadata.get("whiteboard_edited", {}).get("correction_id", entry_id)
        fields = {"actor": actor, "actor_type": actor_type, "entry_type": "note", "content": content,
                  "metadata": {"whiteboard_edit": {"entry_id": entry_id, "previous_entry_id": previous}},
                  "task_id": original.task_id, "handoff_id": original.handoff_id, "run_id": original.run_id,
                  "room_id": original.room_id}
        if actor_id:
            fields["actor_id"] = actor_id
        return self.service.append_whiteboard(identity, **fields)

    def delete_preview(self, identity):
        from threaddesk.services.trash import TrashService
        return {**TrashService(self.store).preview(kind="thread", object_id=identity),
                "whiteboard_id": identity, "lifecycle_scope": "owning_thread",
                "required_confirmation": "confirm_thread_move=true",
                "notice": "Whiteboard und zugehöriger Thread samt Notizen werden gemeinsam verborgen; Originaldateien bleiben erhalten."}

    def delete(self, identity, *, confirm_thread_move, operation_id, expected_revision):
        if confirm_thread_move is not True:
            raise ManagementError("explicit_confirmation_required", "Verschieben des zugehörigen Threads ausdrücklich bestätigen.")
        from threaddesk.services.trash import TrashService
        return TrashService(self.store).move(kind="thread", object_id=identity,
                    operation_id=operation_id, expected_revision=expected_revision)

    def restore(self, *, trash_id, generation, expected_revision, operation_id):
        from threaddesk.services.trash import TrashService
        trash = TrashService(self.store)
        entry = trash.get(trash_id)
        if entry["kind"] != "thread":
            raise ManagementError("validation_error", "Whiteboard-Wiederherstellung benötigt den Thread-Papierkorbeintrag.")
        return trash.restore(trash_id=trash_id, generation=generation,
                    expected_revision=expected_revision, operation_id=operation_id)

    def graph_nodes(self):
        result = []
        for thread in self.store.list_threads(include_archived=True):
            if not self.exists(thread):
                continue
            identity = PREFIX + thread.id
            try:
                self.store.get_node(identity, include_trashed=True)
            except NotFound:
                pass
            else:
                raise ManagementError("graph_projection_conflict", "Whiteboardprojektion kollidiert mit gespeichertem Knoten.", object_id=identity, thread_id=thread.id)
            board = self.get(thread.id)
            result.append(KnowledgeNode(id=PREFIX + thread.id, kind="whiteboard", title=thread.title,
                status="archived" if thread.status == "archived" else "paused" if board["state"] == "closed" else "active",
                details=thread.description, created_at=thread.created_at, updated_at=thread.updated_at,
                revision=thread.revision, source="threaddesk.whiteboard", visibility="private",
                metadata={"thread_id": thread.id, "whiteboard_id": thread.id,
                    "whiteboard_state": board["state"], "whiteboard_status": board["status"],
                    "entry_count": board["entry_count"], "projection": "thread_whiteboard",
                    "lifecycle_scope": "owning_thread"}))
        return result

    def graph_node(self, identity):
        for node in self.graph_nodes():
            if node.id == identity:
                return node
        raise NotFound("Whiteboard-Knoten wurde nicht gefunden.")

    def graph_relations(self, nodes):
        result = []
        boards = {node.metadata["thread_id"]: node for node in nodes
                  if node.kind == "whiteboard" and node.source == "threaddesk.whiteboard"
                  and isinstance(node.metadata.get("thread_id"), str)
                  and node.id == PREFIX + node.metadata["thread_id"]}
        for node in nodes:
            owner = node.metadata.get("thread_id")
            board = boards.get(owner) if isinstance(owner, str) else None
            if board and node.id != board.id:
                result.append(Relation(id="wb-rel-" + board.metadata["thread_id"] + "-" + node.id,
                    source_id=board.id, target_id=node.id, kind="references", created_at=board.created_at,
                    revision=board.revision, source="threaddesk.whiteboard", metadata={"projection": "thread_whiteboard"}))
        return result
