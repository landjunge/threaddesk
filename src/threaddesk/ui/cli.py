from __future__ import annotations

import argparse
import sys

from threaddesk.api.service import ThreadService
from threaddesk.core.errors import ThreadDeskError
from threaddesk.core.models import Thread


def _svc() -> ThreadService:
    return ThreadService()


def _fmt(thread: Thread, current_id: str | None) -> str:
    mark = "*" if thread.id == current_id else " "
    snap = thread.current_snapshot_id or "-"
    return f"{mark} {thread.id}  [{thread.status:8}]  {thread.title}  snap={snap}"


def cmd_new(args: argparse.Namespace) -> int:
    thread = _svc().create(args.title, args.description or "")
    print(f"angelegt und aktiv: {thread.id}  {thread.title}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    svc = _svc()
    current = svc.store.get_current_id()
    rows = svc.list(include_archived=args.all)
    if not rows:
        print("keine threads")
        return 0
    for t in rows:
        print(_fmt(t, current))
    return 0


def cmd_switch(args: argparse.Namespace) -> int:
    thread = _svc().switch(args.id)
    print(f"aktiv: {thread.id}  {thread.title}")
    if thread.context.notes:
        print("--- notizen ---")
        print(thread.context.notes)
    return 0


def cmd_current(_: argparse.Namespace) -> int:
    thread = _svc().current()
    if thread is None:
        print("kein aktiver thread")
        return 1
    print(_fmt(thread, thread.id))
    print(f"beschreibung: {thread.description or '-'}")
    print("--- notizen ---")
    print(thread.context.notes or "(leer)")
    return 0


def cmd_note(args: argparse.Namespace) -> int:
    thread = _svc().set_note(args.text, args.id)
    print(f"notiz gesetzt: {thread.id}")
    return 0


def cmd_rename(args: argparse.Namespace) -> int:
    thread = _svc().rename(args.id, args.title)
    print(f"umbenannt: {thread.id}  {thread.title}")
    return 0


def cmd_archive(args: argparse.Namespace) -> int:
    thread = _svc().archive(args.id)
    print(f"archiviert: {thread.id}")
    return 0


def cmd_delete(args: argparse.Namespace) -> int:
    _svc().delete(args.id)
    print(f"gelöscht: {args.id}")
    return 0


def cmd_snap_save(args: argparse.Namespace) -> int:
    snap = _svc().snapshot(args.label or "", args.id)
    print(f"snapshot: {snap.id}  {snap.label or '(ohne label)'}")
    return 0


def cmd_snap_list(args: argparse.Namespace) -> int:
    snaps = _svc().snapshots(args.id)
    if not snaps:
        print("keine snapshots")
        return 0
    for s in snaps:
        print(f"  {s.id}  {s.created_at}  {s.label or '-'}")
    return 0


def cmd_snap_load(args: argparse.Namespace) -> int:
    thread = _svc().restore(args.snap_id)
    print(f"wiederhergestellt: {thread.id}  snap={thread.current_snapshot_id}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="td", description="ThreadDesk — Kontext halten, nichts ausführen.")
    sub = p.add_subparsers(dest="cmd", required=True)

    n = sub.add_parser("new", help="Thread anlegen und aktivieren")
    n.add_argument("title")
    n.add_argument("-d", "--description", default="")
    n.set_defaults(func=cmd_new)

    ls = sub.add_parser("list", help="Threads listen")
    ls.add_argument("-a", "--all", action="store_true", help="inkl. archivierte")
    ls.set_defaults(func=cmd_list)

    sw = sub.add_parser("switch", help="Thread aktivieren, Kontext wiederherstellen")
    sw.add_argument("id")
    sw.set_defaults(func=cmd_switch)

    cu = sub.add_parser("current", help="Aktiven Thread zeigen")
    cu.set_defaults(func=cmd_current)

    nt = sub.add_parser("note", help="Notiz am (aktiven) Thread setzen")
    nt.add_argument("text")
    nt.add_argument("--id", default=None)
    nt.set_defaults(func=cmd_note)

    rn = sub.add_parser("rename", help="Thread umbenennen")
    rn.add_argument("id")
    rn.add_argument("title")
    rn.set_defaults(func=cmd_rename)

    ar = sub.add_parser("archive", help="Thread archivieren")
    ar.add_argument("id")
    ar.set_defaults(func=cmd_archive)

    de = sub.add_parser("delete", help="Archivierten Thread löschen")
    de.add_argument("id")
    de.set_defaults(func=cmd_delete)

    ss = sub.add_parser("snap", help="Snapshots")
    ssub = ss.add_subparsers(dest="snap_cmd", required=True)
    sv = ssub.add_parser("save", help="Snapshot speichern")
    sv.add_argument("label", nargs="?", default="")
    sv.add_argument("--id", default=None)
    sv.set_defaults(func=cmd_snap_save)
    sl = ssub.add_parser("list", help="Snapshots listen")
    sl.add_argument("--id", default=None)
    sl.set_defaults(func=cmd_snap_list)
    ld = ssub.add_parser("load", help="Snapshot laden")
    ld.add_argument("snap_id")
    ld.set_defaults(func=cmd_snap_load)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except ThreadDeskError as exc:
        print(f"fehler: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
