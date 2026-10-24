"""Local text commands for stored library copies.

Speech recognition, when a browser provides it, only supplies this text.
The command does not start a program and does not read the original files.
"""
from __future__ import annotations

import re

_FIND = re.compile(r"(?i)^(?:finde|suche|find|search)\s+(.+)$")
_OPEN = re.compile(r"(?i)^(?:öffne|oeffne|open)\s+(.+)$")
_ORGANIZE = re.compile(
    r"(?i)^(?:ordne|organize)\s+(.+)\s+(?:zu|into|to)\s+(.+)$"
)


def _select(hits: list[dict], query: str) -> list[dict]:
    """Use one exact filename. Otherwise act only when the search has one hit."""
    folded = " ".join(query.casefold().split())
    exact = [
        hit for hit in hits
        if " ".join(str(hit.get("filename") or "").casefold().split()) == folded
    ]
    if exact:
        return exact
    return hits


def execute(text: str, *, search, reassign) -> dict:
    command = " ".join((text or "").split())
    if not command:
        return {"ok": False, "error": "empty", "hits": []}
    found = _FIND.match(command)
    if found:
        hits = search(found.group(1))
        return {"ok": True, "action": "find", "hits": hits}
    opened = _OPEN.match(command)
    if opened:
        query = opened.group(1)
        hits = search(query)
        if not hits:
            return {"ok": False, "error": "not_found", "hits": []}
        chosen = _select(hits, query)
        if len(chosen) != 1:
            return {"ok": True, "action": "choose", "hits": chosen}
        return {"ok": True, "action": "open", "hits": chosen, "record_id": chosen[0]["id"]}
    organized = _ORGANIZE.match(command)
    if organized:
        query = organized.group(1).strip()
        hits = search(query)
        if not hits:
            return {"ok": False, "error": "not_found", "hits": []}
        chosen = _select(hits, query)
        if len(chosen) != 1:
            return {"ok": True, "action": "choose", "hits": chosen}
        try:
            record = reassign(chosen[0]["id"], organized.group(2).strip())
        except LookupError:
            return {"ok": False, "error": "thread_missing", "hits": chosen}
        return {"ok": True, "action": "organize", "hits": [record]}
    return {"ok": False, "error": "unknown_command", "hits": []}
