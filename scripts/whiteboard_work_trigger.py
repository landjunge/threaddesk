#!/usr/bin/env python3
"""Opt-in bridge from eligible whiteboard outcomes to a ChatGPT Work agent."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Callable
from urllib import error, request
from urllib.parse import urlparse


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
source_root = os.environ.get("THREADDESK_SOURCE_ROOT")
if source_root:
    sys.path.insert(0, source_root)
else:
    sys.path.insert(0, str(SCRIPT_DIR.parent / "src"))

from threaddesk.storage.json_store import JsonStore
from threaddesk.services.whiteboard import list_entries
from whiteboard_terminal_relay import eligible_terminals


API_ORIGIN = "https://api.chatgpt.com"
STATE_VERSION = 1
DEFAULT_KEYCHAIN_SERVICE = "de.netzwerkpunkt.threaddesk.workspace-agent"
CHANNEL_PATTERN = re.compile(r"agtch_[A-Za-z0-9_-]+\Z")
CONVERSATION_PATTERN = re.compile(r"[A-Za-z0-9._:-]{1,200}\Z")
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}\Z")
REPO_REF_PATTERN = re.compile(
    r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@refs/heads/[A-Za-z0-9._/-]+\Z"
)
REPORT_REF_PATTERN = re.compile(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*\Z")


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def idempotency_key(thread: str, entry_id: str) -> str:
    digest = hashlib.sha256(f"{thread}\0{entry_id}".encode()).hexdigest()
    return f"td-wb-{digest}"


def _short_string(value: object, limit: int = 500) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if value and len(value) <= limit else None


def structured_event(entry, repo_ref: str = "") -> dict:
    """Build the only data allowed to leave the local whiteboard."""
    result = {
        "schema": "threaddesk.work-trigger.v1",
        "event": {
            "entry_id": entry.id,
            "entry_type": entry.entry_type,
            "task_id": entry.task_id,
        },
    }
    evidence = {}
    commit = _short_string(entry.metadata.get("commit_sha"), 40)
    if (
        entry.metadata.get("push_verified") is True
        and commit is not None
        and COMMIT_PATTERN.fullmatch(commit)
    ):
        evidence["commit_sha"] = commit
        evidence["push_verified"] = True
        verified_repo = _short_string(repo_ref)
        if verified_repo and REPO_REF_PATTERN.fullmatch(verified_repo):
            evidence["repo"] = verified_repo
    report = _short_string(entry.metadata.get("report_ref"))
    if (
        entry.metadata.get("report_verified") is True
        and report
        and REPORT_REF_PATTERN.fullmatch(report)
    ):
        evidence["report_ref"] = report
        evidence["report_verified"] = True
    if evidence:
        result["evidence"] = evidence
    return result


def _request_body(payload: dict, conversation_key: str) -> dict:
    return {
        "conversation_key": conversation_key,
        "input": json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ),
    }


def request_body(entry, conversation_key: str, repo_ref: str = "") -> dict:
    return _request_body(structured_event(entry, repo_ref), conversation_key)


def trusted_conversation_url(value: object) -> str | None:
    if not isinstance(value, str) or len(value) > 1000:
        return None
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "chatgpt.com"
        or not parsed.path.startswith("/c/")
        or len(parsed.path) <= 3
        or parsed.fragment
    ):
        return None
    return value


def load_keychain_token(
    channel_id: str, service: str = DEFAULT_KEYCHAIN_SERVICE
) -> str | None:
    """Read only the deliberately provisioned Workspace Agent token entry."""
    try:
        completed = subprocess.run(
            [
                "/usr/bin/security",
                "find-generic-password",
                "-w",
                "-s",
                service,
                "-a",
                channel_id,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    token = completed.stdout.strip()
    return token or None


class _RejectRedirects(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _open_without_redirect(message, timeout: float):
    return request.build_opener(_RejectRedirects()).open(message, timeout=timeout)


def post_trigger(
    channel_id: str,
    token: str,
    body: dict,
    key: str,
    *,
    opener=_open_without_redirect,
    timeout: float = 20,
) -> tuple[int, object]:
    """Perform one fixed-origin request. Callers must provide the secret."""
    if not CHANNEL_PATTERN.fullmatch(channel_id):
        raise ValueError("invalid_channel_id")
    url = f"{API_ORIGIN}/v1/workspace_agents/{channel_id}/trigger"
    message = request.Request(
        url,
        data=json.dumps(body, separators=(",", ":")).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Idempotency-Key": key,
        },
    )
    try:
        with opener(message, timeout=timeout) as response:
            status = response.status
            raw = response.read(65537)
    except error.HTTPError as exc:
        return exc.code, None
    if len(raw) > 65536:
        return status, None
    try:
        return status, json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return status, None


def _new_state(root: Path, thread: str, terminals: list) -> dict:
    return {
        "version": STATE_VERSION,
        "root": str(root.resolve()),
        "thread": thread,
        "baseline_ids": sorted(item.id for item in terminals),
        "events": {},
        "created_at": utc(),
    }


def _load_state(path: Path, root: Path, thread: str, terminals: list) -> tuple[dict, bool]:
    if not path.exists():
        return _new_state(root, thread, terminals), True
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("version") != STATE_VERSION:
        raise ValueError("unsupported_state_version")
    if state.get("root") != str(root.resolve()) or state.get("thread") != thread:
        raise ValueError("state_identity_mismatch")
    if not isinstance(state.get("events"), dict):
        raise ValueError("invalid_state")
    return state, False


def _summary(state: dict, status: str, **extra) -> dict:
    counts = Counter(item.get("status") for item in state["events"].values())
    result = {
        "status": status,
        "pending": counts["pending"],
        "accepted": counts["accepted"],
        "error": counts["error"],
    }
    result.update(extra)
    return result


def state_status(state_path: Path) -> dict:
    state = json.loads(state_path.read_text(encoding="utf-8"))
    accepted = []
    for entry_id, item in state.get("events", {}).items():
        if item.get("status") == "accepted":
            accepted.append(
                {
                    "entry_id": entry_id,
                    "conversation_url": item.get("conversation_url"),
                }
            )
    return _summary(
        state,
        "ok",
        root=state.get("root"),
        thread=state.get("thread"),
        accepted_events=accepted,
        checked_at=state.get("checked_at"),
    )


def work_trigger_once(
    root: Path,
    thread: str,
    state_path: Path,
    *,
    channel_id: str = "",
    conversation_key: str = "",
    repo_ref: str = "",
    bootstrap: bool = False,
    dry_run: bool = False,
    token_provider: Callable[[str], str | None] = load_keychain_token,
    sender: Callable[[str, str, dict, str], tuple[int, object]] = post_trigger,
) -> dict:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with state_path.with_suffix(state_path.suffix + ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        entries = list_entries(JsonStore(root), thread)
        terminals = eligible_terminals(entries)
        state, initialized = _load_state(state_path, root, thread, terminals)
        if initialized:
            state["checked_at"] = utc()
            atomic_json(state_path, state)
            return _summary(
                state,
                "initialized",
                baseline_count=len(state["baseline_ids"]),
            )
        if bootstrap:
            state["checked_at"] = utc()
            atomic_json(state_path, state)
            return _summary(
                state,
                "initialized",
                baseline_count=len(state["baseline_ids"]),
            )

        known = set(state.get("baseline_ids", ())) | set(state["events"])
        discovered = []
        for entry in terminals:
            if entry.id in known:
                continue
            payload = structured_event(entry, repo_ref)
            state["events"][entry.id] = {
                "status": "pending",
                "task_id": entry.task_id,
                "entry_type": entry.entry_type,
                "idempotency_key": idempotency_key(thread, entry.id),
                "payload": payload,
                "request": _request_body(payload, conversation_key),
                "attempts": 0,
                "discovered_at": utc(),
            }
            known.add(entry.id)
            discovered.append(entry.id)
            atomic_json(state_path, state)

        if CONVERSATION_PATTERN.fullmatch(conversation_key):
            verified_repo = _short_string(repo_ref)
            for item in state["events"].values():
                if item["status"] == "accepted" or item["attempts"]:
                    continue
                payload = item["payload"]
                evidence = payload.get("evidence")
                if (
                    evidence
                    and evidence.get("push_verified") is True
                    and verified_repo
                    and REPO_REF_PATTERN.fullmatch(verified_repo)
                ):
                    evidence["repo"] = verified_repo
                item["request"] = _request_body(payload, conversation_key)
            atomic_json(state_path, state)

        if dry_run:
            state["checked_at"] = utc()
            atomic_json(state_path, state)
            previews = [
                {"entry_id": item_id, "request": state["events"][item_id]["request"]}
                for item_id in state["events"]
                if state["events"][item_id]["status"] != "accepted"
            ]
            return _summary(
                state,
                "dry_run",
                discovered=discovered,
                requests=previews,
                submitted=False,
            )

        config_errors = []
        if not CHANNEL_PATTERN.fullmatch(channel_id):
            config_errors.append("channel_id")
        if not CONVERSATION_PATTERN.fullmatch(conversation_key):
            config_errors.append("conversation_key")
        if config_errors:
            state["checked_at"] = utc()
            atomic_json(state_path, state)
            return _summary(
                state,
                "configuration_missing",
                missing=config_errors,
                discovered=discovered,
                submitted=False,
            )

        token = token_provider(channel_id)
        if not token:
            state["checked_at"] = utc()
            atomic_json(state_path, state)
            return _summary(
                state,
                "configuration_missing",
                missing=["workspace_agent_token"],
                discovered=discovered,
                submitted=False,
            )

        submitted = []
        failed = []
        for entry_id, item in state["events"].items():
            if item["status"] == "accepted":
                continue
            item["attempts"] += 1
            item["last_attempt_at"] = utc()
            atomic_json(state_path, state)
            try:
                status_code, response = sender(
                    channel_id,
                    token,
                    item["request"],
                    item["idempotency_key"],
                )
            except Exception as exc:  # keep exception text, headers and tokens out of state/logs
                item["status"] = "error"
                item["last_error"] = f"transport_{type(exc).__name__}"
                failed.append(entry_id)
                atomic_json(state_path, state)
                continue
            conversation_url = None
            if isinstance(response, dict):
                conversation_url = trusted_conversation_url(response.get("conversation_url"))
            if status_code == 202 and conversation_url:
                item["status"] = "accepted"
                item["accepted_at"] = utc()
                item["conversation_url"] = conversation_url
                item.pop("last_error", None)
                submitted.append(entry_id)
            else:
                item["status"] = "error"
                item["last_error"] = (
                    "invalid_accepted_response"
                    if status_code == 202
                    else f"http_{status_code}"
                )
                failed.append(entry_id)
            atomic_json(state_path, state)

        state["checked_at"] = utc()
        atomic_json(state_path, state)
        return _summary(
            state,
            "ok" if not failed else "error",
            discovered=discovered,
            submitted_entry_ids=submitted,
            failed_entry_ids=failed,
            submitted=bool(submitted),
            chatgpt_current_conversation_received=False,
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["bootstrap", "once", "status"])
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--thread", required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--channel-id", default="")
    parser.add_argument("--conversation-key", default="")
    parser.add_argument("--repo-ref", default="")
    parser.add_argument("--keychain-service", default=DEFAULT_KEYCHAIN_SERVICE)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        if args.action == "status":
            result = state_status(args.state)
        else:
            provider = lambda channel: load_keychain_token(  # noqa: E731
                channel, args.keychain_service
            )
            result = work_trigger_once(
                args.root,
                args.thread,
                args.state,
                channel_id=args.channel_id,
                conversation_key=args.conversation_key,
                repo_ref=args.repo_ref,
                bootstrap=args.action == "bootstrap",
                dry_run=args.dry_run,
                token_provider=provider,
            )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 2 if result["status"] in {"configuration_missing", "error"} else 0
    except Exception as exc:
        print(
            json.dumps(
                {"status": "error", "reason": type(exc).__name__},
                ensure_ascii=False,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
