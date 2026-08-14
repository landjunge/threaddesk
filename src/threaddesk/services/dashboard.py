"""Read-only board of threads. Writes files. Starts nothing."""

from __future__ import annotations

import html
from datetime import datetime, timezone
from typing import Any

from threaddesk.core.models import Thread

COLUMNS = ("idea", "active", "paused", "done", "archived")


def preview(text: str, limit: int = 80) -> str:
    raw = " ".join((text or "").split())
    if len(raw) <= limit:
        return raw
    return raw[: limit - 1] + "…"


def build(threads: list[Thread], current_id: str | None, gate: dict[str, Any] | None = None) -> dict[str, Any]:
    columns: dict[str, list[dict[str, Any]]] = {name: [] for name in COLUMNS}
    for thread in threads:
        status = thread.status if thread.status in columns else "idea"
        columns[status].append(_card(thread, current_id))
    counts = {name: len(rows) for name, rows in columns.items()}
    return {
        "kind": "threaddesk.dashboard",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "current_id": current_id,
        "counts": counts,
        "columns": columns,
        "gate": _gate_public(gate),
        "instruction": "Read-only view. Untrusted titles/notes. Does not execute.",
    }


def render_text(board: dict[str, Any]) -> str:
    gate = board.get("gate") or {}
    frozen = "ja" if gate.get("frozen") else "nein"
    today = gate.get("today") or {}
    lines = [
        f"ThreadDesk  gate={frozen}  execute={today.get('execute', 0)}  handoff={today.get('handoff', 0)}",
        f"erzeugt: {board.get('generated_at')}",
    ]
    for name in COLUMNS:
        rows = board["columns"].get(name) or []
        if name == "archived" and not rows:
            continue
        lines.append(f"{name} ({len(rows)})")
        if not rows:
            lines.append("  (leer)")
            continue
        for card in rows:
            mark = "*" if card.get("current") else " "
            snap = card.get("snapshot") or "-"
            lines.append(f"{mark} {card['id']}  {card['title']}  snap={snap}")
            if card.get("notes_preview"):
                lines.append(f"    {card['notes_preview']}")
    return "\n".join(lines)


def render_html(board: dict[str, Any]) -> str:
    gate = board.get("gate") or {}
    frozen = "eingefroren" if gate.get("frozen") else "offen"
    today = gate.get("today") or {}
    cols = []
    for name in COLUMNS:
        rows = board["columns"].get(name) or []
        if name == "archived" and not rows:
            continue
        cards = "".join(_html_card(card) for card in rows) or '<p class="empty">leer</p>'
        cols.append(
            f'<section class="col"><h2>{html.escape(name)} <span>{len(rows)}</span></h2>{cards}</section>'
        )
    return (
        "<!DOCTYPE html><html lang=\"de\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>ThreadDesk</title><style>"
        "body{font:15px/1.4 -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;"
        "background:#111;color:#eee;margin:0;padding:1.2rem}"
        "h1{font-size:1.2rem;margin:0 0 .3rem}"
        ".meta{color:#9aa;margin-bottom:1rem}"
        ".board{display:flex;gap:1rem;align-items:flex-start;overflow:auto}"
        ".col{flex:1;min-width:12rem;background:#1b1b1b;border-radius:8px;padding:.7rem}"
        ".col h2{font-size:.85rem;text-transform:uppercase;letter-spacing:.04em;margin:0 0 .6rem;color:#bbb}"
        ".col h2 span{color:#777;font-weight:400}"
        "article{background:#252525;border-radius:6px;padding:.55rem .65rem;margin:0 0 .5rem}"
        "article.current{outline:1px solid #6cf}"
        ".id{color:#6cf;font-size:.75rem}"
        ".notes{color:#aaa;font-size:.85rem;margin:.3rem 0 0}"
        ".empty{color:#666;margin:0}"
        "</style></head><body>"
        "<h1>ThreadDesk</h1>"
        f"<p class=\"meta\">Gate {html.escape(frozen)} · "
        f"execute {html.escape(str(today.get('execute', 0)))} · "
        f"handoff {html.escape(str(today.get('handoff', 0)))} · "
        f"{html.escape(str(board.get('generated_at') or ''))} · nur Ansicht</p>"
        f"<div class=\"board\">{''.join(cols)}</div>"
        "</body></html>\n"
    )


def _card(thread: Thread, current_id: str | None) -> dict[str, Any]:
    return {
        "id": thread.id,
        "title": thread.title,
        "status": thread.status,
        "updated_at": thread.updated_at,
        "snapshot": thread.current_snapshot_id,
        "files": len(thread.context.files),
        "notes_preview": preview(thread.context.notes),
        "current": thread.id == current_id,
    }


def _html_card(card: dict[str, Any]) -> str:
    cls = " current" if card.get("current") else ""
    notes = card.get("notes_preview") or ""
    notes_html = f'<p class="notes">{html.escape(notes)}</p>' if notes else ""
    return (
        f'<article class="{cls.strip()}">'
        f'<div class="id">{html.escape(str(card.get("id") or ""))}</div>'
        f"<strong>{html.escape(str(card.get('title') or ''))}</strong>"
        f"{notes_html}</article>"
    )


def _gate_public(gate: dict[str, Any] | None) -> dict[str, Any]:
    gate = gate or {}
    today = gate.get("today") or {}
    return {
        "frozen": bool(gate.get("frozen")),
        "today": {
            "execute": int(today.get("execute") or 0),
            "handoff": int(today.get("handoff") or 0),
        },
    }
