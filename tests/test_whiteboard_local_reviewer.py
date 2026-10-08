from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import plistlib
import subprocess

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.storage.json_store import JsonStore


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "whiteboard_local_reviewer.py"
SPEC = importlib.util.spec_from_file_location("whiteboard_local_reviewer", SCRIPT)
reviewer = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(reviewer)


@pytest.fixture
def binding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    root = tmp_path / "board"
    service = ThreadService(JsonStore(root))
    thread = service.create("Reviewer test").id
    repo = tmp_path / "fixed-target"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    monkeypatch.setattr(reviewer, "FIXED_REPO", repo.resolve())
    return {
        "root": root,
        "service": service,
        "thread": thread,
        "repo": repo,
        "state": tmp_path / "private-state" / "state.json",
    }


def add_task(binding: dict, task_id: str = "task-1", **changes) -> dict:
    fields = {
        "actor": "Kira",
        "actor_type": "chatgpt",
        "entry_type": "task",
        "content": changes.pop("content", "Authorized work"),
        "task_id": task_id,
        "metadata": changes.pop("metadata", {"runner": "codex-v1"}),
    }
    fields.update(changes)
    return binding["service"].append_whiteboard(binding["thread"], **fields)["entry"]


def add_terminal(
    binding: dict,
    task_id: str = "task-1",
    entry_type: str = "result",
    **changes,
) -> dict:
    task_entries = [
        item
        for item in binding["service"].whiteboard(binding["thread"])
        if item.entry_type == "task" and item.task_id == task_id
    ]
    default_run_id = (
        f"codex-{task_entries[-1].id}-aaaaaaaaaaaa"
        if task_entries
        else "codex-000000000000-aaaaaaaaaaaa"
    )
    fields = {
        "actor": changes.pop("actor", "Codex"),
        "actor_type": changes.pop("actor_type", "codex"),
        "entry_type": entry_type,
        "content": changes.pop("content", "Finished"),
        "task_id": task_id,
        "run_id": changes.pop("run_id", default_run_id),
        "metadata": changes.pop(
            "metadata", {"commit_sha": "a" * 40, "push_verified": True}
        ),
    }
    fields.update(changes)
    return binding["service"].append_whiteboard(binding["thread"], **fields)["entry"]


def answer(status: str = "reviewed", **changes) -> str:
    value = {
        "status": status,
        "summary": "The bounded evidence was inspected.",
        "evidence": ["Commit-shaped evidence is present."],
        "reservations": [],
        "recommendation": "Kira should decide whether this is sufficient.",
    }
    value.update(changes)
    return json.dumps(value)


def run(binding: dict, executor, **kwargs) -> dict:
    return reviewer.review_once(
        binding["root"],
        binding["thread"],
        binding["repo"],
        binding["state"],
        executor=executor,
        **kwargs,
    )


def notes(binding: dict) -> list:
    return [
        item
        for item in binding["service"].whiteboard(binding["thread"])
        if item.metadata.get("role") == "reviewer"
    ]


def test_install_baselines_old_history_and_new_terminal_reviews_once(binding: dict) -> None:
    add_task(binding, "old")
    old = add_terminal(binding, "old")
    baseline = reviewer.baseline(
        binding["root"], binding["thread"], binding["repo"], binding["state"]
    )
    calls = []

    assert baseline["baseline_count"] == 1
    assert run(binding, lambda *args: calls.append(args) or answer())["reviewed_count"] == 0

    add_task(binding, "new")
    new = add_terminal(binding, "new")
    first = run(binding, lambda evidence, repo: calls.append((evidence, repo)) or answer())
    second = run(binding, lambda *args: calls.append(args) or answer())

    assert old["id"] != new["id"]
    assert len(calls) == 1
    assert first["processed_source_id"] == new["id"]
    assert first["reviewed_count"] == 1
    assert second["reviewed_count"] == 1
    assert len(notes(binding)) == 1


def test_unauthorized_and_late_task_id_replays_are_ignored(binding: dict) -> None:
    add_task(binding, "unmarked", metadata={})
    add_terminal(binding, "unmarked")
    add_terminal(binding, "late")
    add_task(binding, "late")
    add_task(binding, "shadowed")
    add_task(binding, "shadowed", metadata={})
    add_terminal(binding, "shadowed")
    calls = []

    result = run(binding, lambda *args: calls.append(args) or answer())

    assert calls == []
    assert result["reviewed_count"] == 0
    assert notes(binding) == []


def test_run_id_must_match_task_when_authorization_binds_one(binding: dict) -> None:
    add_task(binding, "bound", run_id="expected-run")
    add_terminal(binding, "bound", run_id="other-run")
    calls = []

    result = run(binding, lambda *args: calls.append(args) or answer())

    assert calls == []
    assert result["pending_count"] == 0


def test_daily_budget_is_reserved_before_spawn_and_fourth_is_deferred(binding: dict) -> None:
    calls = []
    for number in range(4):
        task_id = f"task-{number}"
        add_task(binding, task_id)
        add_terminal(binding, task_id)
        result = run(
            binding,
            lambda evidence, repo: calls.append(evidence["source_entry_id"]) or answer(),
            day_provider=lambda: "2026-10-08",
        )

    assert len(calls) == 3
    assert result["deferred"] == "daily_limit"
    assert result["daily_runs"] == 3
    state = json.loads(binding["state"].read_text())
    assert state["daily_runs"]["2026-10-08"] == 3
    assert sum(item["status"] == "pending" for item in state["sources"].values()) == 1


def test_process_lock_allows_only_one_reviewer(binding: dict) -> None:
    add_task(binding)
    add_terminal(binding)
    binding["state"].parent.mkdir(parents=True)
    lock_path = binding["state"].with_suffix(".json.lock")
    with lock_path.open("a") as lock:
        import fcntl

        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = run(binding, lambda *args: answer())

    assert result["status"] == "busy"
    assert notes(binding) == []


def test_restart_marks_running_failed_without_retry(binding: dict) -> None:
    add_task(binding)
    terminal = add_terminal(binding)
    identity = reviewer._identity(
        binding["root"].resolve(), binding["thread"], binding["repo"].resolve()
    )
    state = reviewer._new_state(identity)
    state["status"] = "running"
    state["active"] = terminal["id"]
    state["daily_runs"] = {"2026-10-08": 1}
    state["sources"][terminal["id"]] = {
        "status": "running",
        "task_id": "task-1",
        "run_id": terminal["run_id"],
    }
    reviewer.atomic_json(binding["state"], state)
    calls = []

    result = run(binding, lambda *args: calls.append(args) or answer())

    assert calls == []
    assert result["failed_count"] == 1
    recovered = json.loads(binding["state"].read_text())["sources"][terminal["id"]]
    assert recovered["failure"] == "interrupted_previous_run"


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        json.dumps(
            {
                "status": "reviewed",
                "summary": "No",
                "evidence": [],
                "reservations": [],
                "recommendation": "No",
                "unexpected": True,
            }
        ),
        answer(summary="x" * (reviewer.MAX_SUMMARY_CHARS + 1)),
    ],
)
def test_invalid_output_fails_without_false_review(binding: dict, raw: str) -> None:
    add_task(binding)
    add_terminal(binding)

    result = run(binding, lambda *args: raw)

    assert result["failed_count"] == 1
    assert result["reviewed_count"] == 0
    assert notes(binding) == []


def test_timeout_is_failed_and_never_retried(binding: dict) -> None:
    add_task(binding)
    add_terminal(binding)
    calls = []

    def timeout(*args):
        calls.append(args)
        raise TimeoutError("review_timeout")

    first = run(binding, timeout)
    second = run(binding, timeout)

    assert len(calls) == 1
    assert first["failed_count"] == 1
    assert second["failed_count"] == 1
    assert notes(binding) == []


def test_real_executor_timeout_terminates_the_whole_process_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    signals = []

    class FakeProcess:
        pid = 4321
        returncode = None

        def communicate(self, prompt, timeout):
            assert timeout == 300
            raise subprocess.TimeoutExpired(["codex"], timeout)

        def wait(self, timeout):
            self.returncode = -15
            return self.returncode

    monkeypatch.setattr(reviewer.shutil, "which", lambda value: "/usr/bin/codex")
    monkeypatch.setattr(reviewer.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())
    monkeypatch.setattr(
        reviewer.os, "killpg", lambda pid, sent_signal: signals.append((pid, sent_signal))
    )

    with pytest.raises(TimeoutError, match="review_timeout"):
        reviewer.execute_codex(
            {"source_entry_id": "source", "source_entry_type": "result"}, tmp_path
        )

    assert signals == [(4321, reviewer.signal.SIGTERM)]


def test_prompt_uses_structured_allowlist_not_source_or_shell(binding: dict) -> None:
    attack = "$(touch /tmp/nope); `id`; private-value-do-not-copy " + "x" * 7_800
    add_task(binding, content=attack)
    terminal = add_terminal(binding, content=attack, metadata={"private": attack})
    observed = {}

    def execute(evidence, repo):
        observed["evidence"] = evidence
        observed["prompt"] = reviewer.build_prompt(evidence)
        observed["command"] = reviewer.build_command(
            "/usr/bin/codex", repo, Path("/private/schema.json"), Path("/private/out.json")
        )
        return answer(status="inconclusive")

    result = run(binding, execute)

    assert result["reviewed_count"] == 1
    assert terminal["id"] in observed["prompt"]
    assert attack not in observed["prompt"]
    assert len(observed["prompt"]) <= reviewer.MAX_PROMPT_CHARS
    assert all(attack not in argument for argument in observed["command"])
    command = observed["command"]
    assert command[:7] == [
        "/usr/bin/codex",
        "-a",
        "never",
        "--sandbox",
        "read-only",
        "--model",
        "gpt-5.6-sol",
    ]
    assert 'model_reasoning_effort="medium"' in command
    assert "features.multi_agent=false" in command
    assert 'web_search="disabled"' in command
    assert "--add-dir" not in command
    assert "--ignore-user-config" in command
    assert command[-1] == "-"


def test_reviewer_note_is_recommendation_only_and_never_retriggers(binding: dict) -> None:
    add_task(binding, "blocked")
    source = add_terminal(
        binding,
        "blocked",
        entry_type="problem",
        actor="Runner",
        actor_type="system",
        metadata={"runner": "codex-v1", "reason": "timeout"},
    )
    calls = []

    first = run(
        binding,
        lambda evidence, repo: calls.append(evidence) or answer(
            recommendation="Keep the blocker open pending evidence."
        ),
    )
    second = run(binding, lambda *args: calls.append(args) or answer())

    assert first["reviewed_count"] == 1
    assert second["reviewed_count"] == 1
    assert len(calls) == 1
    note = notes(binding)[0]
    assert note.entry_type == "note"
    assert note.actor == "Lokaler Reviewer"
    assert note.actor_type == "codex"
    assert note.metadata == {
        "role": "reviewer",
        "recommendation_only": True,
        "chatgpt_received": False,
        "source_entry_id": source["id"],
        "reviewer_status": "reviewed",
    }
    assert note.external_key == f"wb-local-review:{source['id']}:v1"


def test_private_state_permissions(binding: dict) -> None:
    reviewer.baseline(
        binding["root"], binding["thread"], binding["repo"], binding["state"]
    )

    assert binding["state"].stat().st_mode & 0o777 == 0o600
    assert binding["state"].parent.stat().st_mode & 0o777 == 0o700


def test_fixed_repo_cannot_be_selected_by_input(binding: dict, tmp_path: Path) -> None:
    other = tmp_path / "other-repo"
    other.mkdir()
    subprocess.run(["git", "init", "-q", str(other)], check=True)

    with pytest.raises(ValueError, match="repo_must_match_fixed_target"):
        reviewer.review_once(
            binding["root"],
            binding["thread"],
            other,
            binding["state"],
            executor=lambda *args: answer(),
        )


def test_install_writes_exact_launchd_contract_after_baseline(
    binding: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    add_task(binding, "historic")
    add_terminal(binding, "historic")
    folder = tmp_path / "installed"
    plist = tmp_path / "LaunchAgents" / "reviewer.plist"
    label = "de.netzwerkpunkt.threaddesk.local-reviewer." + binding["thread"]
    monkeypatch.setattr(reviewer.sys, "platform", "darwin")
    monkeypatch.setattr(reviewer, "paths", lambda thread: (folder, label, plist))
    monkeypatch.setattr(reviewer, "_resolved_python", lambda: Path("/usr/bin/python3"))
    monkeypatch.setattr(reviewer.shutil, "which", lambda value: "/usr/local/bin/codex")
    real_run = subprocess.run

    def fake_run(command, *args, **kwargs):
        if command[0] == "/bin/launchctl":
            return subprocess.CompletedProcess(command, 0, "", "")
        return real_run(command, *args, **kwargs)

    monkeypatch.setattr(reviewer.subprocess, "run", fake_run)

    result = reviewer.install(
        binding["root"], binding["thread"], binding["repo"], "codex"
    )

    config = plistlib.loads(plist.read_bytes())
    state = json.loads((folder / "state.json").read_text())
    assert result["baseline_count"] == 1
    assert result["status"] == "idle"
    assert result["model"] == "gpt-5.6-sol"
    assert result["reasoning_effort"] == "medium"
    assert config["Label"] == label
    assert config["StartInterval"] == 15
    assert config["RunAtLoad"] is True
    assert config["ProgramArguments"][0] == "/usr/bin/python3"
    assert config["ProgramArguments"][2] == "once"
    assert state["status"] == "idle"
    assert state["daily_runs"] == {}
    assert (folder / "whiteboard_local_reviewer.py").read_bytes() == SCRIPT.read_bytes()


def test_failed_install_does_not_leave_launch_agent(
    binding: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "installed"
    plist = tmp_path / "LaunchAgents" / "reviewer.plist"
    monkeypatch.setattr(reviewer.sys, "platform", "darwin")
    monkeypatch.setattr(reviewer, "paths", lambda thread: (folder, "test.reviewer", plist))
    monkeypatch.setattr(reviewer, "_resolved_python", lambda: Path("/usr/bin/python3"))
    monkeypatch.setattr(reviewer.shutil, "which", lambda value: "/usr/local/bin/codex")
    real_run = subprocess.run

    def fake_run(command, *args, **kwargs):
        if command[0] == "/bin/launchctl":
            return subprocess.CompletedProcess(command, 5, "", "failed")
        return real_run(command, *args, **kwargs)

    monkeypatch.setattr(reviewer.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="launchd_bootstrap_failed"):
        reviewer.install(binding["root"], binding["thread"], binding["repo"])

    assert not plist.exists()
    assert not (folder / "whiteboard_local_reviewer.py").exists()
    assert (folder / "state.json").exists()  # durable baseline/state is preserved
