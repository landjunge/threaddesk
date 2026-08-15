from __future__ import annotations

import argparse
import sys
from pathlib import Path

from threaddesk.api.service import ThreadService
from threaddesk.core.errors import ThreadDeskError
from threaddesk.core.models import Thread


def _svc() -> ThreadService:
    return ThreadService()


def _fmt(thread: Thread, current_id: str | None, index: int | None = None) -> str:
    mark = "*" if thread.id == current_id else " "
    snap = thread.current_snapshot_id or "-"
    num = f"{index:>2}." if index is not None else "   "
    return f"{mark}{num} {thread.id}  [{thread.status:8}]  {thread.title}  snap={snap}"


def _print_context(thread: Thread) -> None:
    print(f"beschreibung: {thread.description or '-'}")
    print(f"status: {thread.status}  snap: {thread.current_snapshot_id or '-'}")
    if thread.context.files:
        print("--- dateien ---")
        for path in thread.context.files:
            print(f"  {path}")
    print("--- notizen ---")
    print(thread.context.notes or "(leer)")


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
    for i, t in enumerate(rows, 1):
        print(_fmt(t, current, i))
    return 0


def cmd_switch(args: argparse.Namespace) -> int:
    if not args.id:
        return cmd_list(argparse.Namespace(all=False))
    thread = _svc().switch(args.id)
    print(f"aktiv: {thread.id}  {thread.title}")
    _print_context(thread)
    return 0


def cmd_current(_: argparse.Namespace) -> int:
    thread = _svc().current()
    if thread is None:
        print("kein aktiver thread")
        return 1
    print(_fmt(thread, thread.id, None))
    _print_context(thread)
    return 0


def cmd_note(args: argparse.Namespace) -> int:
    thread = _svc().set_note(args.text, args.id, append=args.append)
    print(f"notiz gesetzt: {thread.id}")
    return 0


def cmd_describe(args: argparse.Namespace) -> int:
    thread = _svc().set_description(args.text, args.id)
    print(f"beschreibung gesetzt: {thread.id}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    thread = _svc().set_status(args.status, args.id)
    print(f"status {thread.status}: {thread.id}")
    return 0


def cmd_files(args: argparse.Namespace) -> int:
    svc = _svc()
    if args.files_cmd == "ls":
        thread = svc.get(args.id) if args.id else svc.current()
        if thread is None:
            print("kein aktiver thread", file=sys.stderr)
            return 1
        if not thread.context.files:
            print("keine dateien")
            return 0
        for path in thread.context.files:
            print(path)
        return 0
    if args.files_cmd == "add":
        thread = svc.add_file(args.path, args.id)
        print(f"datei: {args.path}  ({thread.id})")
        return 0
    thread = svc.remove_file(args.path, args.id)
    print(f"entfernt: {args.path}  ({thread.id})")
    return 0


def cmd_rename(args: argparse.Namespace) -> int:
    thread = _svc().rename(args.id, args.title)
    print(f"umbenannt: {thread.id}  {thread.title}")
    return 0


def cmd_archive(args: argparse.Namespace) -> int:
    thread = _svc().archive(args.id)
    print(f"archiviert: {thread.id}")
    return 0


def cmd_unarchive(args: argparse.Namespace) -> int:
    thread = _svc().unarchive(args.id)
    print(f"wieder offen (paused): {thread.id}")
    return 0


def cmd_delete(args: argparse.Namespace) -> int:
    if not args.yes:
        print("löschen nur mit --yes (vorher td archive)", file=sys.stderr)
        return 2
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


def cmd_handoff(args: argparse.Namespace) -> int:
    payload = _svc().handoff(args.id)
    print(payload["path"])
    return 0


def cmd_mcp(_: argparse.Namespace) -> int:
    from threaddesk.ui.mcp_stdio import serve

    serve()
    return 0


def cmd_grok(args: argparse.Namespace) -> int:
    mode = "execute" if args.execute else "brainstorm"
    packet = _svc().grok(mode=mode, variant=args.variant, key=args.id)
    print(packet["prompt"])
    print("---")
    print(packet["command"])
    print(f"paket: {packet['path']}  (grok nicht gestartet)")
    return 0


def cmd_gnom(args: argparse.Namespace) -> int:
    mode = "execute" if args.execute else "brainstorm"
    packet = _svc().gnom(mode=mode, variant=args.variant, key=args.id)
    print(packet["prompt"])
    print("---")
    print(packet["command"])
    print(f"paket: {packet['path']}  (gnom nicht gestartet, nichts gesendet)")
    return 0


def _print_gate(status: dict) -> None:
    policy = status["policy"]
    today = status["today"]
    print(f"frozen: {'ja' if status['frozen'] else 'nein'}  tag: {status['day']}")
    print(
        f"execute heute: {today['execute']}/{policy['max_execute_day']}  "
        f"pro thread: {policy['max_execute_thread_day']}"
    )
    print(
        f"handoff heute: {today['handoff']}/{policy['max_handoff_day']}  "
        f"pro thread: {policy['max_handoff_thread_day']}"
    )
    print(f"cooldown: {policy['cooldown_seconds']}s")
    last = status.get("last") or {}
    if last.get("at"):
        print(f"zuletzt: {last.get('action')}  {last.get('thread_id')}  {last.get('at')}")


def cmd_dash(args: argparse.Namespace) -> int:
    board = _svc().dashboard(include_archived=args.all)
    print(board["text"])
    print(f"html: {board['html_path']}")
    if args.open:
        import webbrowser

        webbrowser.open(Path(board["html_path"]).resolve().as_uri())
        print("browser geöffnet (keine Agenten)")
    return 0


def cmd_gate(args: argparse.Namespace) -> int:
    svc = _svc()
    cmd = args.gate_cmd or "status"
    if cmd == "status":
        _print_gate(svc.gate())
        return 0
    if cmd == "check":
        got = svc.gate_check(args.action, args.id)
        print(("ok" if got["allow"] else "block") + f"  {got['action']}")
        if got["reason"]:
            print(got["reason"])
        else:
            print(f"remaining thread={got['remaining_thread']}  day={got['remaining_day']}")
        return 0 if got["allow"] else 2
    if cmd == "freeze":
        _print_gate(svc.gate_freeze(True))
        return 0
    if cmd == "unfreeze":
        _print_gate(svc.gate_freeze(False))
        return 0
    _print_gate(
        svc.gate_set(
            max_execute_day=args.max_execute_day,
            max_execute_thread_day=args.max_execute_thread_day,
            max_handoff_day=args.max_handoff_day,
            max_handoff_thread_day=args.max_handoff_thread_day,
            cooldown_seconds=args.cooldown,
        )
    )
    return 0


def cmd_prompt(args: argparse.Namespace) -> int:
    svc = _svc()
    if args.list_prompts:
        items = svc.prompts(args.id)
        if not items:
            print("keine gespeicherten prompts")
            return 0
        for item in items:
            print(f"{item.get('id')}  {item.get('created_at')}  {item.get('target')}/{item.get('variant')}")
        return 0
    text = svc.prompt(args.target, args.variant, args.id, save=args.save)
    print(text)
    if args.save:
        print("\n--- gespeichert im thread ---")
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

    sw = sub.add_parser("switch", help="Thread aktivieren (id, Nummer oder Titel)")
    sw.add_argument("id", nargs="?", help="ohne Argument: Liste")
    sw.set_defaults(func=cmd_switch)

    cu = sub.add_parser("current", help="Aktiven Thread inkl. Kontext zeigen")
    cu.set_defaults(func=cmd_current)

    nt = sub.add_parser("note", help="Notiz setzen (überschreibt, außer -a)")
    nt.add_argument("text")
    nt.add_argument("--id", default=None)
    nt.add_argument("-a", "--append", action="store_true")
    nt.set_defaults(func=cmd_note)

    ds = sub.add_parser("describe", help="Beschreibung setzen")
    ds.add_argument("text")
    ds.add_argument("--id", default=None)
    ds.set_defaults(func=cmd_describe)

    st = sub.add_parser("status", help="idea | active | paused | done")
    st.add_argument("status")
    st.add_argument("--id", default=None)
    st.set_defaults(func=cmd_status)

    fl = sub.add_parser("files", help="Dateipfade im Kontext (kein Inhalt)")
    fls = fl.add_subparsers(dest="files_cmd", required=True)
    fls.add_parser("ls").set_defaults(func=cmd_files, id=None)
    fa = fls.add_parser("add")
    fa.add_argument("path")
    fa.add_argument("--id", default=None)
    fa.set_defaults(func=cmd_files)
    fr = fls.add_parser("rm")
    fr.add_argument("path")
    fr.add_argument("--id", default=None)
    fr.set_defaults(func=cmd_files)
    # ls needs optional --id
    fls.choices["ls"].add_argument("--id", default=None)

    rn = sub.add_parser("rename", help="Thread umbenennen")
    rn.add_argument("id")
    rn.add_argument("title")
    rn.set_defaults(func=cmd_rename)

    ar = sub.add_parser("archive", help="Thread archivieren")
    ar.add_argument("id")
    ar.set_defaults(func=cmd_archive)

    ua = sub.add_parser("unarchive", help="Archiv holen (wird paused)")
    ua.add_argument("id")
    ua.set_defaults(func=cmd_unarchive)

    de = sub.add_parser("delete", help="Archivierten Thread löschen")
    de.add_argument("id")
    de.add_argument("--yes", action="store_true")
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

    pr = sub.add_parser("prompt", help="Prompt aus Thread-Kontext bauen (führt nichts aus)")
    pr.add_argument("--target", default="grok", choices=["grok", "gnom", "generic"])
    pr.add_argument("--variant", default="detailed", choices=["short", "detailed", "steps", "agent"])
    pr.add_argument("--save", action="store_true", help="im Thread speichern")
    pr.add_argument("--id", default=None)
    pr.add_argument("--list", dest="list_prompts", action="store_true")
    pr.set_defaults(func=cmd_prompt)

    ho = sub.add_parser("handoff", help="Lokales Handoff-JSON für Gnom-Hub (startet nichts)")
    ho.add_argument("--id", default=None)
    ho.set_defaults(func=cmd_handoff)

    mp = sub.add_parser("mcp", help="MCP-Server auf stdin/stdout (nur Thread-Daten)")
    mp.set_defaults(func=cmd_mcp)

    gk = sub.add_parser("grok", help="Grok-Build-Paket schreiben (startet Grok nicht)")
    gk.add_argument("--execute", action="store_true", help="Execute-Paket, immer noch kein Start")
    gk.add_argument("--variant", default="detailed", choices=["short", "detailed", "steps", "agent"])
    gk.add_argument("--id", default=None)
    gk.set_defaults(func=cmd_grok)

    gn = sub.add_parser("gnom", help="gnom-hub-v1-Paket schreiben (startet und sendet nichts)")
    gn.add_argument("--execute", action="store_true", help="chat + /api/execute, immer noch kein POST")
    gn.add_argument("--variant", default="detailed", choices=["short", "detailed", "steps", "agent"])
    gn.add_argument("--id", default=None)
    gn.set_defaults(func=cmd_gnom)

    gt = sub.add_parser("gate", help="Lokaler Loop-/Tages-Schutz (kein Tollgate-Start)")
    gts = gt.add_subparsers(dest="gate_cmd")
    gt.set_defaults(func=cmd_gate)
    gts.add_parser("status").set_defaults(func=cmd_gate)
    chk = gts.add_parser("check")
    chk.add_argument("--action", default="execute", choices=["execute", "handoff"])
    chk.add_argument("--id", default=None)
    chk.set_defaults(func=cmd_gate)
    gts.add_parser("freeze").set_defaults(func=cmd_gate)
    gts.add_parser("unfreeze").set_defaults(func=cmd_gate)
    st = gts.add_parser("set")
    st.add_argument("--max-execute-day", type=int, default=None)
    st.add_argument("--max-execute-thread-day", type=int, default=None)
    st.add_argument("--max-handoff-day", type=int, default=None)
    st.add_argument("--max-handoff-thread-day", type=int, default=None)
    st.add_argument("--cooldown", type=int, default=None)
    st.set_defaults(func=cmd_gate)

    da = sub.add_parser("dash", help="Nur-Lese-Tafel (HTML + Terminal, kein Server)")
    da.add_argument("-a", "--all", action="store_true", help="inkl. archivierte")
    da.add_argument("--open", action="store_true", help="HTML lokal im Browser öffnen")
    da.set_defaults(func=cmd_dash)
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
