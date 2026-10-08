#!/usr/bin/env python3
"""Small local result/problem relay. Queues a Kira handoff, never claims ChatGPT receipt."""
from __future__ import annotations
import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

src = os.environ.get("THREADDESK_SOURCE_ROOT")
if src:
    sys.path.insert(0, src)
else:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from threaddesk.storage.json_store import JsonStore
from threaddesk.services.whiteboard import append, list_entries

def utc() -> str:
    return datetime.now(timezone.utc).isoformat()

def atomic_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)

def eligible_terminals(entries: list) -> list:
    authorized = set()
    terminals = []
    for entry in entries:
        if (
            entry.entry_type == "task"
            and entry.actor_type == "chatgpt"
            and entry.metadata.get("runner") == "codex-v1"
            and entry.task_id
        ):
            authorized.add(entry.task_id)
            continue
        if entry.task_id not in authorized:
            continue
        if entry.actor_type == "codex" and entry.entry_type in {"result", "problem"}:
            terminals.append(entry)
        elif (
            entry.actor_type == "system"
            and entry.entry_type == "problem"
            and entry.metadata.get("runner") == "codex-v1"
        ):
            terminals.append(entry)
    return terminals

def send_local_notice() -> bool:
    # Never embed untrusted whiteboard text in the notification's executable code.
    script = ('var a=Application.currentApplication();a.includeStandardAdditions=true;'
              'a.displayNotification("Neuer Abschluss oder Blocker im Whiteboard. Bitte ThreadDesk prüfen.",'
              '{withTitle:"ThreadDesk – Übergabe für Kira"});')
    try:
        r = subprocess.run(["/usr/bin/osascript", "-l", "JavaScript", "-e", script],
                           capture_output=True, text=True, timeout=12)
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False

def relay_once(root: Path, thread: str, state_path: Path, *, bootstrap: bool = False,
               replay_task: str = "", notifier=send_local_notice) -> dict:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with state_path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        store = JsonStore(root)
        entries = list_entries(store, thread)
        terminals = eligible_terminals(entries)
        identity = {"root": str(root.resolve()), "thread": thread}
        if state_path.exists():
            state = json.loads(state_path.read_text(encoding="utf-8"))
            if any(state.get(k) != v for k, v in identity.items()):
                raise ValueError("Result watcher belongs to a different whiteboard")
        else:
            # Safe first start: historic terminals are not new messages.
            state = {**identity, "seen": [e.id for e in terminals if e.task_id != replay_task],
                     "pending_notices": [], "queued_count": 0}
        if bootstrap:
            atomic_json(state_path, state)
            return {"status": "initialized", "baseline_count": len(state["seen"]),
                    "replay_task": replay_task}
        seen = set(state["seen"])
        new = []
        for item in terminals:
            if item.id in seen:
                continue
            # A pending review is NOT a receipt by a ChatGPT session.
            _, dup = append(store, thread, actor="WB-Ergebnisweitergabe", actor_type="system",
                    entry_type="note",
                    content=(f"{utc()} Für Kira zur Prüfung vorgemerkt: {item.entry_type.upper()} "
                             f"für task_id={item.task_id}, Quelle={item.id}, run_id={item.run_id or '-'}."
                             " Noch keine Zustellung an diesen Chat und keine Prüfbestätigung."),
                    task_id=item.task_id, run_id=item.run_id,
                    metadata={"handoff_to": "Kira", "handoff_state": "pending_review",
                              "chatgpt_received": False, "source_entry_id": item.id,
                              "source_entry_type": item.entry_type},
                    external_key=f"wb-terminal-relay:{item.id}")
            seen.add(item.id)
            state["queued_count"] = state.get("queued_count", 0) + (0 if dup else 1)
            state["pending_notices"].append(item.id)
            new.append(item.id)
            # Durable after each entry; restart cannot lose already queued handoff.
            state["seen"] = sorted(seen)
            atomic_json(state_path, state)
        notice_ok = None
        if state["pending_notices"]:
            notice_ok = bool(notifier())
            if notice_ok:
                state["pending_notices"] = []
        state["checked_at"] = utc()
        state["seen"] = sorted(seen)
        atomic_json(state_path, state)
        return {"status": "ok", "new_terminal_ids": new,
                "queue_total": state.get("queued_count", 0),
                "pending_local_notifications": len(state["pending_notices"]),
                "notification_submitted": notice_ok,
                "chatgpt_received": False}

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["once", "bootstrap", "status"])
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--thread", required=True)
    p.add_argument("--state", type=Path, required=True)
    p.add_argument("--replay-task", default="")
    a = p.parse_args()
    try:
        if a.action == "status":
            result = json.loads(a.state.read_text(encoding="utf-8"))
            result = {k:v for k,v in result.items() if k != "seen"}
        else:
            result = relay_once(a.root, a.thread, a.state, bootstrap=a.action=="bootstrap",
                                replay_task=a.replay_task)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as e:
        print(json.dumps({"status": "error", "reason": str(e)}, ensure_ascii=False))
        raise SystemExit(1)
