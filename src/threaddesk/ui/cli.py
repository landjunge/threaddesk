from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path

from threaddesk.api.service import ThreadService
from threaddesk.core import i18n
from threaddesk.core.errors import ThreadDeskError
from threaddesk.core.models import Thread

Translator = Callable[..., str]


def _svc() -> ThreadService:
    return ThreadService()


def _translator(language: str,
                register: str = i18n.DEFAULT_REGISTER) -> Translator:
    """Bindet Sprache und Sprachebene einmal, damit kein Aufruf sie vergisst."""

    def translate(key: str, **values: object) -> str:
        return i18n.translate(key, language, register, **values)

    return translate


def _lang(args: argparse.Namespace) -> Translator:
    return _translator(getattr(args, "lang", i18n.DEFAULT_LANGUAGE),
                       getattr(args, "mode", i18n.DEFAULT_REGISTER))


def _flag_value(argv: list[str], flag: str) -> str | None:
    """Liest `--flag wert` oder `--flag=wert` aus argv."""
    for index, item in enumerate(argv):
        if item == flag and index + 1 < len(argv):
            return argv[index + 1]
        if item.startswith(flag + "="):
            return item.split("=", 1)[1]
    return None


def resolve_language(argv: list[str]) -> str:
    """Sprache schon vor dem Parsen bestimmen.

    argparse baut die Hilfetexte beim Anlegen des Parsers, nicht erst beim
    Parsen. Deshalb muss --lang vorher aus argv gelesen werden, sonst waere
    `td --lang en --help` wieder deutsch.
    """
    chosen = _flag_value(argv, "--lang")
    return i18n.normalise(chosen) if chosen else i18n.from_environment()


def resolve_register(argv: list[str]) -> str:
    """Sprachebene schon vor dem Parsen bestimmen — aus demselben Grund."""
    chosen = _flag_value(argv, "--mode")
    return (i18n.normalise_register(chosen) if chosen
            else i18n.register_from_environment())


def _fmt(thread: Thread, current_id: str | None, index: int | None = None) -> str:
    mark = "*" if thread.id == current_id else " "
    snap = thread.current_snapshot_id or "-"
    num = f"{index:>2}." if index is not None else "   "
    return f"{mark}{num} {thread.id}  [{thread.status:8}]  {thread.title}  snap={snap}"


def _print_context(thread: Thread, t: Translator) -> None:
    print(t("cli.field.description", value=thread.description or "-"))
    print(
        t(
            "cli.field.status",
            status=thread.status,
            snapshot=thread.current_snapshot_id or "-",
        )
    )
    if thread.context.files:
        print(t("cli.section.files"))
        for path in thread.context.files:
            print(f"  {path}")
    print(t("cli.section.notes"))
    print(thread.context.notes or t("cli.notes.empty"))


def cmd_new(args: argparse.Namespace) -> int:
    t = _lang(args)
    thread = _svc().create(args.title, args.description or "")
    print(t("cli.thread.created", id=thread.id, title=thread.title))
    return 0


def _numbers(svc: ThreadService) -> dict[str, int]:
    """Welche Nummer welchem Thread gehoert.

    Eine Nummer muss ueberall dasselbe bedeuten. `td switch 2` loest immer
    gegen die nicht archivierten Threads auf, also darf auch `td list --all`
    nur diese nummerieren. Sonst zeigt die Liste eine Nummer, die woanders
    hinfuehrt — und zwar stillschweigend.

    Archivierte Threads bekommen keine Nummer. Sie bleiben ueber ihre Kennung
    oder ihren Titel erreichbar.
    """
    return {thread.id: number
            for number, thread in enumerate(svc.list(include_archived=False), 1)}


def cmd_list(args: argparse.Namespace) -> int:
    t = _lang(args)
    svc = _svc()
    current = svc.store.get_current_id()
    rows = svc.list(include_archived=args.all)
    if not rows:
        print(t("cli.thread.none"))
        return 0
    numbers = _numbers(svc)
    for thread in rows:
        print(_fmt(thread, current, numbers.get(thread.id)))
    return 0


def cmd_switch(args: argparse.Namespace) -> int:
    t = _lang(args)
    if not args.id:
        return cmd_list(argparse.Namespace(all=False, lang=args.lang))
    thread = _svc().switch(args.id)
    print(t("cli.thread.active", id=thread.id, title=thread.title))
    _print_context(thread, t)
    return 0


def cmd_current(args: argparse.Namespace) -> int:
    t = _lang(args)
    thread = _svc().current()
    if thread is None:
        print(t("cli.thread.no_active"))
        return 1
    print(_fmt(thread, thread.id, None))
    _print_context(thread, t)
    return 0


def cmd_note(args: argparse.Namespace) -> int:
    t = _lang(args)
    thread = _svc().set_note(args.text, args.id, append=args.append)
    print(t("cli.note.saved", id=thread.id))
    return 0


def cmd_describe(args: argparse.Namespace) -> int:
    t = _lang(args)
    thread = _svc().set_description(args.text, args.id)
    print(t("cli.description.saved", id=thread.id))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    t = _lang(args)
    thread = _svc().set_status(args.status, args.id)
    print(t("cli.status.saved", status=thread.status, id=thread.id))
    return 0


def cmd_files(args: argparse.Namespace) -> int:
    t = _lang(args)
    svc = _svc()
    if args.files_cmd == "ls":
        thread = svc.get(args.id) if args.id else svc.current()
        if thread is None:
            print(t("cli.thread.no_active"), file=sys.stderr)
            return 1
        if not thread.context.files:
            print(t("cli.files.none"))
            return 0
        for path in thread.context.files:
            print(path)
        return 0
    if args.files_cmd == "add":
        thread = svc.add_file(args.path, args.id)
        print(t("cli.files.added", path=args.path, id=thread.id))
        return 0
    thread = svc.remove_file(args.path, args.id)
    print(t("cli.files.removed", path=args.path, id=thread.id))
    return 0


def cmd_rename(args: argparse.Namespace) -> int:
    t = _lang(args)
    thread = _svc().rename(args.id, args.title)
    print(t("cli.thread.renamed", id=thread.id, title=thread.title))
    return 0


def cmd_archive(args: argparse.Namespace) -> int:
    t = _lang(args)
    thread = _svc().archive(args.id)
    print(t("cli.thread.archived", id=thread.id))
    return 0


def cmd_unarchive(args: argparse.Namespace) -> int:
    t = _lang(args)
    thread = _svc().unarchive(args.id)
    print(t("cli.thread.unarchived", id=thread.id))
    return 0


def cmd_delete(args: argparse.Namespace) -> int:
    t = _lang(args)
    if not args.yes:
        print(t("cli.thread.delete_guard"), file=sys.stderr)
        return 2
    _svc().delete(args.id)
    print(t("cli.thread.deleted", id=args.id))
    return 0


def cmd_snap_save(args: argparse.Namespace) -> int:
    t = _lang(args)
    snap = _svc().snapshot(args.label or "", args.id)
    print(t("cli.snap.saved", id=snap.id, label=snap.label or t("cli.snap.no_label")))
    return 0


def cmd_snap_list(args: argparse.Namespace) -> int:
    t = _lang(args)
    snaps = _svc().snapshots(args.id)
    if not snaps:
        print(t("cli.snap.none"))
        return 0
    for snap in snaps:
        print(f"  {snap.id}  {snap.created_at}  {snap.label or '-'}")
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
    t = _lang(args)
    mode = "execute" if args.execute else "brainstorm"
    packet = _svc().grok(mode=mode, variant=args.variant, key=args.id)
    print(packet["prompt"])
    print("---")
    print(packet["command"])
    print(t("cli.packet.grok", path=packet["path"]))
    return 0


def cmd_gnom(args: argparse.Namespace) -> int:
    t = _lang(args)
    mode = "execute" if args.execute else "brainstorm"
    packet = _svc().gnom(mode=mode, variant=args.variant, key=args.id)
    print(packet["prompt"])
    print("---")
    print(packet["command"])
    print(t("cli.packet.gnom", path=packet["path"]))
    return 0


def _print_gate(status: dict, t: Translator) -> None:
    policy = status["policy"]
    today = status["today"]
    frozen = t("cli.gate.yes") if status["frozen"] else t("cli.gate.no")
    print(t("cli.gate.frozen", frozen=frozen, day=status["day"]))
    print(
        t(
            "cli.gate.execute_today",
            used=today["execute"],
            limit=policy["max_execute_day"],
            per_thread=policy["max_execute_thread_day"],
        )
    )
    print(
        t(
            "cli.gate.handoff_today",
            used=today["handoff"],
            limit=policy["max_handoff_day"],
            per_thread=policy["max_handoff_thread_day"],
        )
    )
    print(t("cli.gate.cooldown", seconds=policy["cooldown_seconds"]))
    last = status.get("last") or {}
    if last.get("at"):
        print(
            t(
                "cli.gate.last",
                action=last.get("action"),
                thread=last.get("thread_id"),
                at=last.get("at"),
            )
        )


def cmd_dash(args: argparse.Namespace) -> int:
    t = _lang(args)
    board = _svc().dashboard(include_archived=args.all)
    print(board["text"])
    print(t("cli.dash.html", path=board["html_path"]))
    if args.open:
        import webbrowser

        webbrowser.open(Path(board["html_path"]).resolve().as_uri())
        print(t("cli.dash.opened"))
    return 0


def cmd_gate(args: argparse.Namespace) -> int:
    t = _lang(args)
    svc = _svc()
    cmd = args.gate_cmd or "status"
    if cmd == "status":
        _print_gate(svc.gate(), t)
        return 0
    if cmd == "check":
        got = svc.gate_check(args.action, args.id)
        key = "cli.gate.allow" if got["allow"] else "cli.gate.block"
        print(t(key, action=got["action"]))
        if got["reason"]:
            print(got["reason"])
        else:
            print(
                t(
                    "cli.gate.remaining",
                    thread=got["remaining_thread"],
                    day=got["remaining_day"],
                )
            )
        return 0 if got["allow"] else 2
    if cmd == "freeze":
        _print_gate(svc.gate_freeze(True), t)
        return 0
    if cmd == "unfreeze":
        _print_gate(svc.gate_freeze(False), t)
        return 0
    _print_gate(
        svc.gate_set(
            max_execute_day=args.max_execute_day,
            max_execute_thread_day=args.max_execute_thread_day,
            max_handoff_day=args.max_handoff_day,
            max_handoff_thread_day=args.max_handoff_thread_day,
            cooldown_seconds=args.cooldown,
        ),
        t,
    )
    return 0


def cmd_prompt(args: argparse.Namespace) -> int:
    t = _lang(args)
    svc = _svc()
    if args.list_prompts:
        items = svc.prompts(args.id)
        if not items:
            print(t("cli.prompt.none"))
            return 0
        for item in items:
            print(
                f"{item.get('id')}  {item.get('created_at')}  "
                f"{item.get('target')}/{item.get('variant')}"
            )
        return 0
    text = svc.prompt(args.target, args.variant, args.id, save=args.save)
    print(text)
    if args.save:
        print()
        print(t("cli.prompt.stored"))
    return 0


def cmd_snap_load(args: argparse.Namespace) -> int:
    t = _lang(args)
    thread = _svc().restore(args.snap_id)
    print(
        t("cli.snap.restored", id=thread.id, snapshot=thread.current_snapshot_id)
    )
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    t = _lang(args)
    try:
        from threaddesk.ui.server import run
    except ImportError:
        print(t("cli.serve.missing"), file=sys.stderr)
        return 2
    print(t("cli.serve.running", host=args.host, port=args.port))
    if args.open:
        import webbrowser

        webbrowser.open(f"http://{args.host}:{args.port}/")
    run(host=args.host, port=args.port)
    return 0


def cmd_graph(args: argparse.Namespace) -> int:
    payload = _svc().graph(kind=args.kind, status=args.status)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def build_parser(language: str = i18n.DEFAULT_LANGUAGE,
                 register: str = i18n.DEFAULT_REGISTER) -> argparse.ArgumentParser:
    t = _translator(language, register)
    p = argparse.ArgumentParser(prog="td", description=t("cli.description"))
    p.add_argument(
        "--lang",
        default=language,
        choices=list(i18n.LANGUAGES),
        help=t("cli.help.lang"),
    )
    p.add_argument(
        "--mode",
        default=register,
        choices=list(i18n.REGISTERS),
        help=t("cli.help.mode"),
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    n = sub.add_parser("new", help=t("cli.help.new"))
    n.add_argument("title")
    n.add_argument("-d", "--description", default="")
    n.set_defaults(func=cmd_new)

    ls = sub.add_parser("list", help=t("cli.help.list"))
    ls.add_argument("-a", "--all", action="store_true", help=t("cli.help.include_archived"))
    ls.set_defaults(func=cmd_list)

    sw = sub.add_parser("switch", help=t("cli.help.switch"))
    sw.add_argument("id", nargs="?", help=t("cli.help.switch_id"))
    sw.set_defaults(func=cmd_switch)

    cu = sub.add_parser("current", help=t("cli.help.current"))
    cu.set_defaults(func=cmd_current)

    nt = sub.add_parser("note", help=t("cli.help.note"))
    nt.add_argument("text")
    nt.add_argument("--id", default=None)
    nt.add_argument("-a", "--append", action="store_true")
    nt.set_defaults(func=cmd_note)

    ds = sub.add_parser("describe", help=t("cli.help.describe"))
    ds.add_argument("text")
    ds.add_argument("--id", default=None)
    ds.set_defaults(func=cmd_describe)

    st = sub.add_parser("status", help=t("cli.help.status"))
    st.add_argument("status")
    st.add_argument("--id", default=None)
    st.set_defaults(func=cmd_status)

    fl = sub.add_parser("files", help=t("cli.help.files"))
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

    rn = sub.add_parser("rename", help=t("cli.help.rename"))
    rn.add_argument("id")
    rn.add_argument("title")
    rn.set_defaults(func=cmd_rename)

    ar = sub.add_parser("archive", help=t("cli.help.archive"))
    ar.add_argument("id")
    ar.set_defaults(func=cmd_archive)

    ua = sub.add_parser("unarchive", help=t("cli.help.unarchive"))
    ua.add_argument("id")
    ua.set_defaults(func=cmd_unarchive)

    de = sub.add_parser("delete", help=t("cli.help.delete"))
    de.add_argument("id")
    de.add_argument("--yes", action="store_true")
    de.set_defaults(func=cmd_delete)

    ss = sub.add_parser("snap", help=t("cli.help.snap"))
    ssub = ss.add_subparsers(dest="snap_cmd", required=True)
    sv = ssub.add_parser("save", help=t("cli.help.snap_save"))
    sv.add_argument("label", nargs="?", default="")
    sv.add_argument("--id", default=None)
    sv.set_defaults(func=cmd_snap_save)
    sl = ssub.add_parser("list", help=t("cli.help.snap_list"))
    sl.add_argument("--id", default=None)
    sl.set_defaults(func=cmd_snap_list)
    ld = ssub.add_parser("load", help=t("cli.help.snap_load"))
    ld.add_argument("snap_id")
    ld.set_defaults(func=cmd_snap_load)

    pr = sub.add_parser("prompt", help=t("cli.help.prompt"))
    pr.add_argument("--target", default="grok", choices=["grok", "gnom", "generic"])
    pr.add_argument(
        "--variant", default="detailed", choices=["short", "detailed", "steps", "agent"]
    )
    pr.add_argument("--save", action="store_true", help=t("cli.help.prompt_save"))
    pr.add_argument("--id", default=None)
    pr.add_argument("--list", dest="list_prompts", action="store_true")
    pr.set_defaults(func=cmd_prompt)

    ho = sub.add_parser("handoff", help=t("cli.help.handoff"))
    ho.add_argument("--id", default=None)
    ho.set_defaults(func=cmd_handoff)

    mp = sub.add_parser("mcp", help=t("cli.help.mcp"))
    mp.set_defaults(func=cmd_mcp)

    gk = sub.add_parser("grok", help=t("cli.help.grok"))
    gk.add_argument("--execute", action="store_true", help=t("cli.help.grok_execute"))
    gk.add_argument(
        "--variant", default="detailed", choices=["short", "detailed", "steps", "agent"]
    )
    gk.add_argument("--id", default=None)
    gk.set_defaults(func=cmd_grok)

    gn = sub.add_parser("gnom", help=t("cli.help.gnom"))
    gn.add_argument("--execute", action="store_true", help=t("cli.help.gnom_execute"))
    gn.add_argument(
        "--variant", default="detailed", choices=["short", "detailed", "steps", "agent"]
    )
    gn.add_argument("--id", default=None)
    gn.set_defaults(func=cmd_gnom)

    gt = sub.add_parser("gate", help=t("cli.help.gate"))
    gts = gt.add_subparsers(dest="gate_cmd")
    gt.set_defaults(func=cmd_gate)
    gts.add_parser("status").set_defaults(func=cmd_gate)
    chk = gts.add_parser("check")
    chk.add_argument("--action", default="execute", choices=["execute", "handoff"])
    chk.add_argument("--id", default=None)
    chk.set_defaults(func=cmd_gate)
    gts.add_parser("freeze").set_defaults(func=cmd_gate)
    gts.add_parser("unfreeze").set_defaults(func=cmd_gate)
    gset = gts.add_parser("set")
    gset.add_argument("--max-execute-day", type=int, default=None)
    gset.add_argument("--max-execute-thread-day", type=int, default=None)
    gset.add_argument("--max-handoff-day", type=int, default=None)
    gset.add_argument("--max-handoff-thread-day", type=int, default=None)
    gset.add_argument("--cooldown", type=int, default=None)
    gset.set_defaults(func=cmd_gate)

    da = sub.add_parser("dash", help=t("cli.help.dash"))
    da.add_argument("-a", "--all", action="store_true", help=t("cli.help.include_archived"))
    da.add_argument("--open", action="store_true", help=t("cli.help.dash_open"))
    da.set_defaults(func=cmd_dash)

    gr = sub.add_parser("graph", help=t("cli.help.graph"))
    gr.add_argument("--kind", default=None)
    gr.add_argument("--status", default=None)
    gr.set_defaults(func=cmd_graph)

    se = sub.add_parser("serve", aliases=["ui"], help=t("cli.help.serve"))
    se.add_argument("--host", default="127.0.0.1")
    se.add_argument("--port", type=int, default=8765)
    se.add_argument("--open", action="store_true", help=t("cli.help.serve_open"))
    se.set_defaults(func=cmd_serve)
    return p


def main(argv: list[str] | None = None) -> int:
    items = sys.argv[1:] if argv is None else argv
    language = resolve_language(items)
    register = resolve_register(items)
    parser = build_parser(language, register)
    args = parser.parse_args(items)
    try:
        return int(args.func(args))
    except ThreadDeskError as exc:
        print(i18n.translate("cli.error", args.lang, args.mode, message=exc),
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
