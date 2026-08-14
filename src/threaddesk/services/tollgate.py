"""Local cost/loop gate. Does not import or start the Tollgate product."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from threaddesk.core.errors import GateBlocked, InvalidState

ACTIONS = ("execute", "handoff")

DEFAULT_POLICY: dict[str, Any] = {
    "max_execute_day": 30,
    "max_execute_thread_day": 8,
    "max_handoff_day": 60,
    "max_handoff_thread_day": 20,
    "cooldown_seconds": 15,
    "frozen": False,
}

POLICY_INTS = (
    "max_execute_day",
    "max_execute_thread_day",
    "max_handoff_day",
    "max_handoff_thread_day",
    "cooldown_seconds",
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class LocalGate:
    def __init__(self, root: Path, now: Callable[[], datetime] | None = None) -> None:
        self.path = Path(root) / "gate.json"
        self._now = now or _utc_now

    def status(self) -> dict[str, Any]:
        data = self._load()
        now = self._now()
        day = _day_key(now)
        bucket = data["days"].get(day) or _empty_day()
        return {
            "kind": "threaddesk.gate",
            "policy": dict(data["policy"]),
            "frozen": bool(data["policy"]["frozen"]),
            "day": day,
            "today": {
                "execute": int(bucket.get("execute") or 0),
                "handoff": int(bucket.get("handoff") or 0),
            },
            "last": dict(data.get("last") or {}),
            "path": str(self.path),
        }

    def check(self, action: str, thread_id: str) -> dict[str, Any]:
        action = _action(action)
        data = self._load()
        now = self._now()
        reason = self._blocked(data, action, thread_id, now)
        policy = data["policy"]
        day = _day_key(now)
        bucket = data["days"].get(day) or _empty_day()
        thread_row = (bucket.get("threads") or {}).get(thread_id) or {}
        used = int(thread_row.get(action) or 0)
        cap = int(policy[f"max_{action}_thread_day"])
        return {
            "allow": reason is None,
            "action": action,
            "thread_id": thread_id,
            "reason": reason or "",
            "remaining_thread": max(0, cap - used),
            "remaining_day": max(0, int(policy[f"max_{action}_day"]) - int(bucket.get(action) or 0)),
            "frozen": bool(policy["frozen"]),
        }

    def record(self, action: str, thread_id: str) -> dict[str, Any]:
        action = _action(action)
        data = self._load()
        now = self._now()
        reason = self._blocked(data, action, thread_id, now)
        if reason:
            raise GateBlocked(reason)
        day = _day_key(now)
        bucket = data["days"].setdefault(day, _empty_day())
        bucket[action] = int(bucket.get(action) or 0) + 1
        threads = bucket.setdefault("threads", {})
        row = threads.setdefault(thread_id, {"execute": 0, "handoff": 0})
        row[action] = int(row.get(action) or 0) + 1
        data["last"] = {
            "action": action,
            "thread_id": thread_id,
            "at": now.isoformat(),
        }
        self._save(data)
        return self.check(action, thread_id)

    def set_policy(self, **updates: Any) -> dict[str, Any]:
        data = self._load()
        policy = data["policy"]
        for key, value in updates.items():
            if value is None:
                continue
            if key == "frozen":
                policy["frozen"] = bool(value)
                continue
            if key not in POLICY_INTS:
                raise InvalidState(f"unbekanntes gate-feld: {key}")
            number = int(value)
            if number < 0:
                raise InvalidState(f"{key} muss >= 0 sein")
            policy[key] = number
        self._save(data)
        return self.status()

    def freeze(self, frozen: bool = True) -> dict[str, Any]:
        return self.set_policy(frozen=frozen)

    def _blocked(self, data: dict[str, Any], action: str, thread_id: str, now: datetime) -> str | None:
        policy = data["policy"]
        if policy.get("frozen"):
            return "Gate eingefroren. td gate unfreeze"
        last = data.get("last") or {}
        cooldown = int(policy.get("cooldown_seconds") or 0)
        if cooldown and last.get("at"):
            try:
                last_at = datetime.fromisoformat(str(last["at"]))
                if last_at.tzinfo is None:
                    last_at = last_at.replace(tzinfo=timezone.utc)
                elapsed = (now - last_at).total_seconds()
                if elapsed < cooldown:
                    wait = int(cooldown - elapsed) + 1
                    return f"Cooldown {wait}s. Loop-Schutz."
            except ValueError:
                pass
        day = _day_key(now)
        bucket = data["days"].get(day) or _empty_day()
        used_day = int(bucket.get(action) or 0)
        cap_day = int(policy[f"max_{action}_day"])
        if used_day >= cap_day:
            return f"Tageslimit {action} {used_day}/{cap_day}"
        thread_row = (bucket.get("threads") or {}).get(thread_id) or {}
        used_thread = int(thread_row.get(action) or 0)
        cap_thread = int(policy[f"max_{action}_thread_day"])
        if used_thread >= cap_thread:
            return f"Thread-Limit {action} {used_thread}/{cap_thread}"
        return None

    def _load(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {"policy": dict(DEFAULT_POLICY), "last": {}, "days": {}}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"policy": dict(DEFAULT_POLICY), "last": {}, "days": {}, "corrupt": True}
        if not isinstance(raw, dict):
            return {"policy": dict(DEFAULT_POLICY), "last": {}, "days": {}, "corrupt": True}
        policy = dict(DEFAULT_POLICY)
        incoming = raw.get("policy") if isinstance(raw.get("policy"), dict) else {}
        for key in DEFAULT_POLICY:
            if key not in incoming:
                continue
            if key == "frozen":
                policy["frozen"] = bool(incoming[key])
            else:
                try:
                    policy[key] = max(0, int(incoming[key]))
                except (TypeError, ValueError):
                    pass
        days = raw.get("days") if isinstance(raw.get("days"), dict) else {}
        last = raw.get("last") if isinstance(raw.get("last"), dict) else {}
        return {"policy": policy, "last": last, "days": days}

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        payload = {
            "policy": data["policy"],
            "last": data.get("last") or {},
            "days": data.get("days") or {},
        }
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.path)


def _action(action: str) -> str:
    action = (action or "").strip().lower()
    if action not in ACTIONS:
        raise InvalidState(f"action: {', '.join(ACTIONS)}")
    return action


def _day_key(now: datetime) -> str:
    return now.astimezone(timezone.utc).strftime("%Y-%m-%d")


def _empty_day() -> dict[str, Any]:
    return {"execute": 0, "handoff": 0, "threads": {}}
