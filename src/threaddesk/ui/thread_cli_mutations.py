"""Compatibility adapter for immediate human CLI thread edits."""
from __future__ import annotations

from uuid import uuid4

from threaddesk.core.errors import ManagementError
from threaddesk.services.thread_management import manage


def change(svc, args, action, data=None, *, key=None):
    """Always use CAS and an operation receipt, with explicit replay options.

    An immediate legacy CLI edit reads its target once before attempting the
    change. Automation supplies both flags to bind a previously read version;
    it must never silently retry a stale edit with a fresh revision.
    """
    expected = getattr(args, "expected_revision", None)
    operation = getattr(args, "operation_id", None)
    request = {"operation_id": operation or uuid4().hex, "action": action,
               "data": data or {}}
    if action == "create":
        request["expected_revision"] = 0 if expected is None else expected
    else:
        if operation and expected is None:
            raise ManagementError("precondition_required", "--operation-id benötigt --expected-revision.")
        if operation and not key:
            raise ManagementError("precondition_required", "--operation-id benötigt eine exakte Thread-ID.")
        if expected is not None and key:
            # Let manage() check an existing receipt before looking up an object
            # which a previous successful operation may already have deleted.
            request.update(id=key, expected_revision=expected)
        else:
            thread = svc.get(key) if key else svc.current()
            if thread is None:
                raise ManagementError("invalid_state", "Kein aktiver Thread.")
            request.update(id=thread.id, expected_revision=thread.revision)
    result = manage(svc, request)
    return result


def add_options(parser):
    parser.add_argument("--expected-revision", type=int)
    parser.add_argument("--operation-id")
