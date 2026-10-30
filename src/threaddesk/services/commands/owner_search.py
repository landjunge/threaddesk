"""Trusted file-owner search remains restricted to the local CLI transport."""
from contextlib import contextmanager
from dataclasses import asdict

from threaddesk.services.commands.model import CommandSpec
from threaddesk.services.commands.schemas import TEXT, ID, BOOL, LIMIT, obj


def specifications():
    def spec(identity, schema, handler, effect="read"):
        return CommandSpec(identity, "local_search", identity.replace(".", " "), schema, handler,
                           effect=effect, scope="workspace.read" if effect == "read" else "workspace.write",
                           allowed_transports=("local", "cli"))
    yield spec("search.status", obj(), lambda svc, a: _status(svc))
    yield spec("search.configure", obj({"enabled": BOOL}, ("enabled",)), _configure, "external")
    yield spec("search.rebuild", obj({"batches": {"type": "integer", "minimum": 1, "maximum": 100}}), _rebuild, "external")
    query = {"query": {**TEXT, "maxLength": 512}, "limit": LIMIT, "project_id": ID,
             "include_archived": BOOL, "pages": {"type": "integer", "minimum": 1, "maximum": 20}}
    yield spec("search.query", obj(query, ("query",)), _query)


@contextmanager
def _service(svc):
    # Only the explicitly allowed local/CLI dispatcher can reach this handler.
    # HTTP/MCP/Room/module inputs can never select or construct this authority.
    from threaddesk.services.search import SearchService, LocalFileOwnerPolicy
    search = SearchService(svc.store, LocalFileOwnerPolicy(svc.store.workspace_path))
    try:
        yield search
    finally:
        search.close()


def _status(svc):
    with _service(svc) as search:
        return search.status()


def _configure(svc, args):
    with _service(svc) as search:
        search.set_enabled(args["enabled"])
        return search.status()


def _rebuild(svc, args):
    with _service(svc) as search:
        for _ in range(args.get("batches", 1)):
            result = search.rebuild_batch()
            if result["status"] not in {"building", "cleaning"}:
                break
        return result


def _query(svc, args):
    with _service(svc) as search:
        pages, cursor = [], None
        for _ in range(args.get("pages", 1)):
            result = search.search(args["query"], limit=args.get("limit", 20), cursor=cursor,
                                   project_id=args.get("project_id"), include_archived=args.get("include_archived", False))
            pages.append(asdict(result))
            cursor = result.next_cursor
            if cursor is None:
                break
        return {"pages": pages, "more_available": cursor is not None,
                "cursor_scope": "this_call_only; increase the explicit pages budget"}
