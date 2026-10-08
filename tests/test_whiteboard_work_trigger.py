from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from threaddesk.api.service import ThreadService
from threaddesk.storage.json_store import JsonStore


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "whiteboard_work_trigger.py"
SPEC = importlib.util.spec_from_file_location("whiteboard_work_trigger", SCRIPT)
trigger = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(trigger)

CHANNEL = "agtch_test_123"
CONVERSATION = "threaddesk:test-thread"


def board(tmp_path):
    root = tmp_path / "board"
    service = ThreadService(JsonStore(root))
    thread = service.create("Work trigger test").id
    state = tmp_path / "trigger" / "state.json"
    return root, service, thread, state


def task(service, thread, task_id="task-1", *, marked=True):
    metadata = {"runner": "codex-v1"} if marked else {}
    return service.append_whiteboard(
        thread,
        actor="Kira",
        actor_type="chatgpt",
        entry_type="task",
        content="Private task text must stay local",
        task_id=task_id,
        metadata=metadata,
    )["entry"]


def terminal(service, thread, task_id="task-1", *, kind="result", metadata=None):
    return service.append_whiteboard(
        thread,
        actor="Codex",
        actor_type="codex",
        entry_type=kind,
        content="Private terminal text must stay local",
        task_id=task_id,
        metadata=metadata or {},
    )["entry"]


def bootstrap(root, thread, state):
    result = trigger.work_trigger_once(root, thread, state, bootstrap=True)
    assert result["status"] == "initialized"


def run(root, thread, state, **changes):
    arguments = {
        "channel_id": CHANNEL,
        "conversation_key": CONVERSATION,
        "token_provider": lambda _channel: "workspace-token",
    }
    arguments.update(changes)
    return trigger.work_trigger_once(root, thread, state, **arguments)


def test_historical_terminal_is_baselined_and_never_sent(tmp_path):
    root, service, thread, state = board(tmp_path)
    task(service, thread, "old")
    terminal(service, thread, "old")
    sent = []

    result = trigger.work_trigger_once(
        root,
        thread,
        state,
        bootstrap=True,
        token_provider=lambda _channel: sent.append("token") or "token",
        sender=lambda *args: sent.append(args) or (202, {}),
    )

    assert result["baseline_count"] == 1
    assert sent == []
    assert json.loads(state.read_text())["events"] == {}


def test_new_authorized_result_is_sent_exactly_once_without_whiteboard_text(tmp_path):
    root, service, thread, state = board(tmp_path)
    bootstrap(root, thread, state)
    task(service, thread)
    source = terminal(
        service,
        thread,
        metadata={"commit_sha": "a" * 40, "push_verified": True},
    )
    calls = []

    def sender(*args):
        calls.append(args)
        return 202, {"conversation_url": "https://chatgpt.com/c/work-result"}

    first = run(
        root,
        thread,
        state,
        repo_ref="landjunge/threaddesk@refs/heads/feature",
        sender=sender,
    )
    second = run(root, thread, state, sender=sender)

    assert first["submitted_entry_ids"] == [source["id"]]
    assert first["accepted"] == 1
    assert second["submitted_entry_ids"] == []
    assert len(calls) == 1
    channel, token, body, key = calls[0]
    assert channel == CHANNEL
    assert token == "workspace-token"
    assert key.startswith("td-wb-")
    cloud_input = json.loads(body["input"])
    assert cloud_input == {
        "schema": "threaddesk.work-trigger.v1",
        "event": {
            "entry_id": source["id"],
            "entry_type": "result",
            "task_id": "task-1",
        },
        "evidence": {
            "commit_sha": "a" * 40,
            "push_verified": True,
            "repo": "landjunge/threaddesk@refs/heads/feature",
        },
    }
    serialized = json.dumps(body)
    assert "Private task text" not in serialized
    assert "Private terminal text" not in serialized


def test_error_retries_with_the_same_idempotency_key(tmp_path):
    root, service, thread, state = board(tmp_path)
    bootstrap(root, thread, state)
    task(service, thread)
    terminal(service, thread, kind="problem")
    keys = []

    def sender(_channel, _token, _body, key):
        keys.append(key)
        if len(keys) == 1:
            return 503, {"error": "not stored"}
        return 202, {"conversation_url": "https://chatgpt.com/c/retried"}

    assert run(root, thread, state, sender=sender)["status"] == "error"
    assert run(root, thread, state, sender=sender)["status"] == "ok"
    assert len(keys) == 2
    assert keys[0] == keys[1]
    saved = next(iter(json.loads(state.read_text())["events"].values()))
    assert saved["status"] == "accepted"
    assert saved["attempts"] == 2


def test_unauthorized_or_too_early_terminal_is_never_sent(tmp_path):
    root, service, thread, state = board(tmp_path)
    bootstrap(root, thread, state)
    terminal(service, thread, "unmarked")
    task(service, thread, "unmarked", marked=False)
    terminal(service, thread, "too-early")
    task(service, thread, "too-early")
    sent = []

    result = run(
        root,
        thread,
        state,
        sender=lambda *args: sent.append(args) or (202, {}),
    )

    assert result["accepted"] == 0
    assert sent == []
    assert json.loads(state.read_text())["events"] == {}


def test_missing_token_keeps_event_pending_and_never_connects(tmp_path):
    root, service, thread, state = board(tmp_path)
    bootstrap(root, thread, state)
    task(service, thread)
    source = terminal(service, thread)
    sent = []

    result = run(
        root,
        thread,
        state,
        token_provider=lambda _channel: None,
        sender=lambda *args: sent.append(args) or (202, {}),
    )

    assert result["status"] == "configuration_missing"
    assert result["pending"] == 1
    assert sent == []
    saved = json.loads(state.read_text())["events"][source["id"]]
    assert saved["status"] == "pending"
    assert saved["attempts"] == 0


def test_missing_config_is_fail_closed_then_first_attempt_uses_new_config(tmp_path):
    root, service, thread, state = board(tmp_path)
    bootstrap(root, thread, state)
    task(service, thread)
    terminal(service, thread)
    calls = []

    first = trigger.work_trigger_once(
        root,
        thread,
        state,
        token_provider=lambda _channel: calls.append("token") or "secret",
        sender=lambda *args: calls.append(args) or (202, {}),
    )

    assert first["status"] == "configuration_missing"
    assert first["pending"] == 1
    assert calls == []

    def sender(_channel, _token, body, key):
        calls.append((body, key))
        return 202, {"conversation_url": "https://chatgpt.com/c/configured"}

    second = run(root, thread, state, sender=sender)

    assert second["accepted"] == 1
    assert calls[0][0]["conversation_key"] == CONVERSATION


def test_dry_run_neither_reads_token_nor_connects(tmp_path):
    root, service, thread, state = board(tmp_path)
    bootstrap(root, thread, state)
    task(service, thread)
    terminal(service, thread)
    calls = []

    result = run(
        root,
        thread,
        state,
        dry_run=True,
        token_provider=lambda _channel: calls.append("token") or "secret",
        sender=lambda *args: calls.append("sender") or (202, {}),
    )

    assert result["status"] == "dry_run"
    assert result["submitted"] is False
    assert len(result["requests"]) == 1
    assert calls == []


def test_202_with_untrusted_or_missing_url_is_not_accepted(tmp_path):
    root, service, thread, state = board(tmp_path)
    bootstrap(root, thread, state)
    task(service, thread)
    source = terminal(service, thread)

    result = run(
        root,
        thread,
        state,
        sender=lambda *_args: (
            202,
            {"conversation_url": "https://chatgpt.com.evil.example/c/no"},
        ),
    )

    assert result["status"] == "error"
    saved = json.loads(state.read_text())["events"][source["id"]]
    assert saved["status"] == "error"
    assert saved["last_error"] == "invalid_accepted_response"
    assert "conversation_url" not in saved


def test_restart_deduplicates_an_accepted_event(tmp_path):
    root, service, thread, state = board(tmp_path)
    bootstrap(root, thread, state)
    task(service, thread)
    terminal(service, thread)
    calls = []

    def sender(*args):
        calls.append(args)
        return 202, {"conversation_url": "https://chatgpt.com/c/once"}

    assert run(root, thread, state, sender=sender)["accepted"] == 1
    reloaded_state = Path(str(state))
    assert run(root, thread, reloaded_state, sender=sender)["accepted"] == 1
    assert len(calls) == 1


def test_token_and_transport_exception_text_are_not_logged_or_persisted(tmp_path):
    root, service, thread, state = board(tmp_path)
    bootstrap(root, thread, state)
    task(service, thread)
    terminal(service, thread)
    secret = "workspace-super-secret-token"

    def sender(_channel, token, _body, _key):
        raise RuntimeError(f"failed with {token}")

    result = run(
        root,
        thread,
        state,
        token_provider=lambda _channel: secret,
        sender=sender,
    )
    combined = json.dumps(result) + state.read_text()

    assert result["status"] == "error"
    assert secret not in combined
    assert "transport_RuntimeError" in combined


def test_system_problem_requires_runner_marker(tmp_path):
    root, service, thread, state = board(tmp_path)
    bootstrap(root, thread, state)
    task(service, thread)
    service.append_whiteboard(
        thread,
        actor="Runner",
        actor_type="system",
        entry_type="problem",
        content="Unmarked system problem",
        task_id="task-1",
    )
    marked = service.append_whiteboard(
        thread,
        actor="Runner",
        actor_type="system",
        entry_type="problem",
        content="Marked system problem",
        task_id="task-1",
        metadata={"runner": "codex-v1"},
    )["entry"]
    calls = []

    def sender(*args):
        calls.append(args)
        return 202, {"conversation_url": "https://chatgpt.com/c/system"}

    result = run(root, thread, state, sender=sender)

    assert result["submitted_entry_ids"] == [marked["id"]]
    assert len(calls) == 1


def test_result_never_claims_to_wake_or_reach_the_current_chat(tmp_path):
    root, service, thread, state = board(tmp_path)
    bootstrap(root, thread, state)
    task(service, thread)
    terminal(service, thread)

    result = run(
        root,
        thread,
        state,
        sender=lambda *_args: (
            202,
            {"conversation_url": "https://chatgpt.com/c/separate-work-chat"},
        ),
    )

    assert result["chatgpt_current_conversation_received"] is False
    assert "wake" not in json.dumps(result).lower()


def test_http_sender_uses_only_fixed_origin_and_required_headers():
    captured = {}

    class Response:
        status = 202

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, _limit):
            return b'{"conversation_url":"https://chatgpt.com/c/test"}'

    def opener(message, timeout):
        captured["message"] = message
        captured["timeout"] = timeout
        return Response()

    status, response = trigger.post_trigger(
        CHANNEL,
        "secret",
        {"conversation_key": CONVERSATION, "input": "{}"},
        "stable-key",
        opener=opener,
    )

    message = captured["message"]
    assert status == 202
    assert response["conversation_url"] == "https://chatgpt.com/c/test"
    assert message.full_url == (
        "https://api.chatgpt.com/v1/workspace_agents/agtch_test_123/trigger"
    )
    assert message.get_header("Authorization") == "Bearer secret"
    assert message.get_header("Idempotency-key") == "stable-key"


def test_http_redirects_are_rejected_instead_of_followed():
    handler = trigger._RejectRedirects()

    assert handler.redirect_request(None, None, 302, "Found", {}, "https://evil") is None
