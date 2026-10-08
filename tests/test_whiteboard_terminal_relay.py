from __future__ import annotations

import importlib.util
from pathlib import Path

from threaddesk.api.service import ThreadService
from threaddesk.storage.json_store import JsonStore

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "whiteboard_terminal_relay.py"
spec = importlib.util.spec_from_file_location("whiteboard_terminal_relay", SCRIPT)
relay = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(relay)


def new_board(tmp_path):
    root = tmp_path / "board"
    svc = ThreadService(JsonStore(root))
    thread = svc.create("Relay test").id
    state = tmp_path / "relay" / "state.json"
    return root, svc, thread, state


def test_historical_results_are_ignored_and_new_result_queued_exactly_once(tmp_path):
    root, svc, thread, state = new_board(tmp_path)
    svc.append_whiteboard(thread, actor="Kira", actor_type="chatgpt", entry_type="task",
                          content="Historic", task_id="old", metadata={"runner": "codex-v1"})
    svc.append_whiteboard(thread, actor="Codex", actor_type="codex", entry_type="problem",
                          content="Historic failure", task_id="old")
    assert relay.relay_once(root, thread, state, bootstrap=True)["baseline_count"] == 1
    assert not relay.relay_once(root, thread, state, notifier=lambda: True)["new_terminal_ids"]
    svc.append_whiteboard(thread, actor="Kira", actor_type="chatgpt", entry_type="task",
                          content="New", task_id="new", metadata={"runner": "codex-v1"})
    svc.append_whiteboard(thread, actor="Codex", actor_type="codex", entry_type="result",
                          content="Done", task_id="new",
                          metadata={"commit_sha": "a" * 40, "push_verified": True})
    first = relay.relay_once(root, thread, state, notifier=lambda: True)
    assert len(first["new_terminal_ids"]) == 1
    assert first["queue_total"] == 1
    assert first["chatgpt_received"] is False
    assert not relay.relay_once(root, thread, state, notifier=lambda: True)["new_terminal_ids"]
    notes = [e for e in JsonStore(root).list_whiteboard(thread)
             if e.metadata.get("handoff_to") == "Kira"]
    assert len(notes) == 1
    assert notes[0].metadata["chatgpt_received"] is False
    assert notes[0].metadata["handoff_state"] == "pending_review"


def test_specific_current_runner_blocker_can_be_replayed_at_install(tmp_path):
    root, svc, thread, state = new_board(tmp_path)
    svc.append_whiteboard(thread, actor="Kira", actor_type="chatgpt", entry_type="task",
                          content="Current", task_id="current", metadata={"runner": "codex-v1"})
    svc.append_whiteboard(thread, actor="Runner", actor_type="system", entry_type="problem",
                          content="Timeout", task_id="current", metadata={"runner": "codex-v1"})
    assert relay.relay_once(root, thread, state, bootstrap=True,
                            replay_task="current")["baseline_count"] == 0
    assert len(relay.relay_once(root, thread, state,
                               notifier=lambda: True)["new_terminal_ids"]) == 1


def test_unmarked_and_unrelated_terminal_entries_are_not_handed_off(tmp_path):
    root, svc, thread, state = new_board(tmp_path)
    relay.relay_once(root, thread, state, bootstrap=True)
    svc.append_whiteboard(thread, actor="Kira", actor_type="chatgpt", entry_type="task",
                          content="No marker", task_id="other")
    svc.append_whiteboard(thread, actor="Codex", actor_type="codex", entry_type="result",
                          content="Unrelated", task_id="other")
    result = relay.relay_once(root, thread, state, notifier=lambda: True)
    assert result["new_terminal_ids"] == []


def test_terminal_before_marked_task_stays_ignored(tmp_path):
    root, svc, thread, state = new_board(tmp_path)
    relay.relay_once(root, thread, state, bootstrap=True)
    svc.append_whiteboard(thread, actor="Codex", actor_type="codex", entry_type="result",
                          content="Too early", task_id="reused")
    svc.append_whiteboard(thread, actor="Kira", actor_type="chatgpt", entry_type="task",
                          content="Later authorization", task_id="reused",
                          metadata={"runner": "codex-v1"})

    result = relay.relay_once(root, thread, state, notifier=lambda: True)

    assert result["new_terminal_ids"] == []


def test_failed_local_notice_remains_pending_and_is_not_reenqueued(tmp_path):
    root, svc, thread, state = new_board(tmp_path)
    relay.relay_once(root, thread, state, bootstrap=True)
    svc.append_whiteboard(thread, actor="Kira", actor_type="chatgpt", entry_type="task",
                          content="Task", task_id="x", metadata={"runner": "codex-v1"})
    svc.append_whiteboard(thread, actor="Codex", actor_type="codex", entry_type="problem",
                          content="Error", task_id="x")
    first = relay.relay_once(root, thread, state, notifier=lambda: False)
    assert first["pending_local_notifications"] == 1
    second = relay.relay_once(root, thread, state, notifier=lambda: True)
    assert second["pending_local_notifications"] == 0
    assert second["queue_total"] == 1
