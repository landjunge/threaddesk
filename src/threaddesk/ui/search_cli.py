"""Local file-owner CLI; intentionally not registered with HTTP/MCP/Room."""
from dataclasses import asdict
import json

from threaddesk.core.search import SearchError
from threaddesk.services.search import LocalFileOwnerPolicy, SearchService


def register_search(subparsers, language, service_factory):
    def text(de, en):
        return de if language == "de" else en

    parser = subparsers.add_parser("search", help=text("Optionale lokale Inhaltssuche", "Optional local content search"))
    parser.add_argument("query", nargs="?", help=text("Wörtliche Suchbegriffe", "Literal search terms"))
    toggle = parser.add_mutually_exclusive_group()
    toggle.add_argument("--enable", action="store_true", help=text("Suche ausdrücklich einschalten", "Explicitly enable search"))
    toggle.add_argument("--disable", action="store_true", help=text("Suche ausschalten", "Disable search"))
    parser.add_argument("--status", action="store_true", help=text("Indexstand anzeigen", "Show index status"))
    parser.add_argument("--rebuild", action="store_true", help=text("Abgeleiteten Index begrenzt neu aufbauen", "Rebuild the derived index in bounded batches"))
    parser.add_argument("--batches", type=int, default=1, help=text("Explizite Aufbau-Batches, 1–1000", "Explicit rebuild batches, 1–1000"))
    parser.add_argument("--limit", type=int, default=20, help=text("Treffer je Seite, 1–100", "Hits per page, 1–100"))
    parser.add_argument("--pages", type=int, default=1, help=text("Seiten in diesem Aufruf, 1–1000", "Pages in this invocation, 1–1000"))
    parser.add_argument("--cursor", help=text("Nur im laufenden Prozess gültig; sonst --pages verwenden", "Valid only in the live process; otherwise use --pages"))
    parser.add_argument("--project", help=text("Projektfilter, keine Rechtevergabe", "Project filter, not an authorization grant"))
    parser.add_argument("--all", action="store_true", help=text("Archivierte einschließen", "Include archived threads"))

    def run(args):
        if not 1 <= args.batches <= 1000 or not 1 <= args.pages <= 1000:
            raise SearchError("invalid_search_budget")
        store = service_factory().store
        search = SearchService(store, LocalFileOwnerPolicy(store.workspace_path))
        try:
            if args.enable or args.disable:
                search.set_enabled(args.enable)
            if args.rebuild:
                for _ in range(args.batches):
                    status = search.rebuild_batch()
                    if status["status"] not in {"cleaning", "building"}:
                        break
            if args.status or args.query is None:
                print(json.dumps(search.status(), ensure_ascii=False))
            if args.query is not None:
                cursor = args.cursor
                for _ in range(args.pages):
                    result = search.search(args.query, limit=args.limit, cursor=cursor,
                                           project_id=args.project, include_archived=args.all)
                    print(json.dumps(asdict(result), ensure_ascii=False))
                    cursor = result.next_cursor
                    if cursor is None:
                        break
            return 0
        finally:
            search.close()
    parser.set_defaults(func=run)
