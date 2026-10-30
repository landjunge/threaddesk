"""Whiteboard lifecycle declarations over existing threads, logs and trash."""
from __future__ import annotations

from threaddesk.core.models import ACTOR_TYPES
from threaddesk.services.commands.model import CommandSpec
from threaddesk.services.commands.schemas import ID, TEXT, REV, BOOL, PAGE, obj, choice, page
from threaddesk.services.whiteboard_lifecycle import WhiteboardService


def specifications():
    def spec(identity, fields, required, handler, *, effect="read", target=None, native=False, description=None):
        return CommandSpec("whiteboard." + identity, "whiteboard", description or "Thread whiteboard " + identity,
            obj(fields, required), handler, effect=effect,
            scope="workspace.read" if effect == "read" else "workspace.write", revision_target=target,
            native_contract=native, affects_index=effect == "data")
    yield spec("boards", {"include_archived": BOOL, **PAGE}, (),
        lambda svc, a: page(WhiteboardService(svc).list(include_archived=a.get("include_archived", False)), a))
    yield spec("get", {"id": ID}, ("id",), lambda svc, a: WhiteboardService(svc).get(a["id"]))
    yield spec("create", {"title": {**TEXT, "minLength": 1}, "description": TEXT}, ("title",),
        lambda svc, a: WhiteboardService(svc).create(**a), effect="data", target="create",
        description="Create a whiteboard with its own owning ThreadDesk thread; title and lifecycle are shared.")
    for action in ("open", "close", "archive", "unarchive"):
        yield spec(action, {"id": ID}, ("id",),
            lambda svc, a, selected=action: getattr(WhiteboardService(svc), selected)(a["id"]),
            effect="data", target="id", description={
                "open": "Persist board state open and select its thread. Read whiteboard.get for the local UI path; no visible window acknowledgement is implied.",
                "close": "Persist whiteboard state closed; reject subsequent contributions until reopened. Does not claim to close a native window.",
                "archive": "Archive the whiteboard and its owning thread together; notes and log remain stored.",
                "unarchive": "Restore the whiteboard's owning thread from archive; its saved open/closed state is preserved."}[action])
    yield spec("rename", {"id": ID, "title": {**TEXT, "minLength": 1}}, ("id", "title"),
        lambda svc, a: WhiteboardService(svc).rename(a["id"], a["title"]), effect="data", target="id",
        description="Rename this whiteboard and its owning thread together.")
    yield spec("edit", {"id": ID, "entry_id": ID,
        "content": {"type": "string", "minLength": 1, "maxLength": 8000}, "actor": TEXT,
        "actor_type": choice(*ACTOR_TYPES), "actor_id": ID}, ("id", "entry_id", "content"),
        lambda svc, a: WhiteboardService(svc).edit(a["id"], **{key: value for key, value in a.items() if key != "id"}),
        effect="data", target="id", description="Correct one contribution by appending a linked correction; original content and provenance remain in whiteboard.list.")
    yield spec("delete_preview", {"id": ID}, ("id",),
        lambda svc, a: WhiteboardService(svc).delete_preview(a["id"]),
        description="Preview all affected data before moving the whiteboard WITH its owning thread to existing trash; no permanent deletion.")
    yield spec("delete", {"id": ID, "confirm_thread_move": {"const": True, "type": "boolean"},
        "operation_id": ID, "expected_revision": REV}, ("id", "confirm_thread_move", "operation_id", "expected_revision"),
        lambda svc, a: WhiteboardService(svc).delete(a["id"], **{key: value for key, value in a.items() if key != "id"}),
        effect="domain", native=True,
        description="Reversibly move the whiteboard WITH its owning thread/notes to trash. Read delete_preview first and explicitly set confirm_thread_move=true. Permanent deletion remains exclusively trash.purge with its preview-bound approval.")
    fields = {"trash_id": TEXT, "generation": {"type": "integer", "minimum": 1},
              "operation_id": ID, "expected_revision": REV}
    yield spec("restore", fields, tuple(fields), lambda svc, a: WhiteboardService(svc).restore(**a),
        effect="domain", native=True, description="Restore the owning thread and whiteboard from an exact trash generation; original IDs and relationships are preserved. For archive restoration use whiteboard.unarchive.")
