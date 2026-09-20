"""G0: validate Authority Event Envelope v1. No graph, no renderer."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable

SCHEMA_PATH = (
    Path(__file__).resolve().parents[3] / "docs" / "authority" / "authority-event-v1.schema.json"
)

SOURCE_TOOLS = frozenset(
    {"gnom-hub-v1", "agent-authority-lab", "tollgate", "4allpass", "threaddesk"}
)

EVENT_TYPES = frozenset(
    {
        "work.started",
        "agent.invoked",
        "delegation.created",
        "tool.intent",
        "tool.result",
        "work.finished",
        "authority.requested",
        "authority.allowed",
        "authority.denied",
        "authority.freeze",
        "authority.unfreeze",
        "budget.checked",
        "budget.charged",
        "loop.detected",
        "request.blocked",
        "consumer.frozen",
        "capability.granted",
        "capability.denied",
        "capability.revoked",
        "graph.imported",
        "incident.opened",
    }
)

REQUIRED = (
    "schema_version",
    "event_id",
    "timestamp",
    "trace_id",
    "span_id",
    "source_tool",
    "event_type",
    "event_hash",
)

FORBIDDEN_KEYS = frozenset(
    {
        "secret",
        "secrets",
        "password",
        "passwd",
        "prompt",
        "prompt_text",
        "credential",
        "credentials",
        "api_key",
        "apikey",
        "token",
        "access_token",
        "refresh_token",
        "raw_token",
        "master_password",
        "private_key",
        "vault_payload",
    }
)

_SECRETISH = re.compile(
    r"(sk-[a-zA-Z0-9]{8,}|password\s*=|api[_-]?key\s*=|bearer\s+[a-zA-Z0-9._\-]{12,})",
    re.I,
)


class AuthorityEventError(ValueError):
    pass


def canonical_bytes(event: dict[str, Any]) -> bytes:
    body = {k: v for k, v in event.items() if k != "event_hash"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "utf-8"
    )


def compute_event_hash(event: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes(event)).hexdigest()


def _walk_keys(obj: Any) -> Iterable[str]:
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k)
            yield from _walk_keys(v)
    elif isinstance(obj, list):
        for item in obj:
            yield from _walk_keys(item)


def _walk_strings(obj: Any) -> Iterable[str]:
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _walk_strings(v)
    elif isinstance(obj, list):
        for item in obj:
            yield from _walk_strings(item)
    elif isinstance(obj, str):
        yield obj


def validate_event(event: dict[str, Any], *, check_hash: bool = True) -> None:
    if not isinstance(event, dict):
        raise AuthorityEventError("event must be an object")
    if event.get("schema_version") != "1":
        raise AuthorityEventError("schema_version must be '1'")
    missing = [k for k in REQUIRED if not event.get(k)]
    if missing:
        raise AuthorityEventError("missing required: " + ", ".join(missing))
    for key in _walk_keys(event):
        if key.lower() in FORBIDDEN_KEYS:
            raise AuthorityEventError(f"forbidden field {key!r}")
    extra = set(event) - set(REQUIRED) - {
        "parent_span_id",
        "workflow_id",
        "project_id",
        "actor",
        "action",
        "resource",
        "capability_id",
        "decision",
        "reason_code",
        "budget_ref",
        "data_labels",
        "result_ref",
        "previous_event_hash",
    }
    if extra:
        raise AuthorityEventError("unknown fields: " + ", ".join(sorted(extra)))
    if event["source_tool"] not in SOURCE_TOOLS:
        raise AuthorityEventError("unknown source_tool")
    if event["event_type"] not in EVENT_TYPES:
        raise AuthorityEventError("unknown event_type")
    decision = event.get("decision")
    if decision not in (None, "ALLOW", "DENY", "FREEZE"):
        raise AuthorityEventError("invalid decision")
    for text in _walk_strings(event):
        if _SECRETISH.search(text):
            raise AuthorityEventError("secret-like value in event")
    if check_hash and event["event_hash"] != compute_event_hash(event):
        raise AuthorityEventError("event_hash mismatch")


def validate_trace(events: list[dict[str, Any]]) -> None:
    if not events:
        raise AuthorityEventError("empty trace")
    seen: set[str] = set()
    prev_hash: str | None = None
    trace_id = events[0].get("trace_id")
    for ev in events:
        validate_event(ev)
        eid = ev["event_id"]
        if eid in seen:
            raise AuthorityEventError(f"duplicate event_id {eid}")
        seen.add(eid)
        if ev.get("trace_id") != trace_id:
            raise AuthorityEventError("trace_id must be shared")
        prev = ev.get("previous_event_hash")
        if prev_hash is None:
            if prev not in (None, ""):
                raise AuthorityEventError("first event must not chain")
        elif prev != prev_hash:
            raise AuthorityEventError("hash chain broken")
        prev_hash = ev["event_hash"]
