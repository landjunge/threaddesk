from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import plistlib
import subprocess

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.services.whiteboard import append
from threaddesk.storage.json_store import JsonStore


MODULE = Path(__file__).resolve().parents[1] / "scripts" / "whiteboard_codex_runner.py"
SPEC = importlib.util.spec_from_file_location("whiteboard_codex_runner", MODULE)
runner = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(runner)


@pytest.fixture
def binding(tmp_path: Path) -> dict:
    root = tmp_path / "whiteboard-root"
    service = ThreadService(JsonStore(root))
    thread = service.create("Runner test")
    repo = tmp_path / "target-repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    return {
        "root": root,
        "thread": thread.id,
        "repo": repo,
        "state": tmp_path / "runner" / "state.json",
        "service": service,
    }


def add_task(binding: dict, content: str = "Do the bounded work", **changes) -> dict:
    fields = {
        "actor": "Kira",
        "actor_type": "chatgpt",
        "entry_type": "task",
        "content": content,
        "task_id": changes.pop("task_id", "task-1"),
        "metadata": changes.pop("metadata", {"runner": "codex-v1"}),
    }
    fields.update(changes)
    return binding["service"].append_whiteboard(binding["thread"], **fields)["entry"]


def append_claim_and_result(config: dict, entry, run_id: str) -> int:
    store = JsonStore(Path(config["root"]))
    append(
        store,
        entry.thread_id,
        actor="Terminal-Codex",
        actor_type="codex",
        entry_type="claimed",
        content="Claimed by the test Codex.",
        task_id=entry.task_id,
        run_id=run_id,
    )
    append(
        store,
        entry.thread_id,
        actor="Terminal-Codex",
        actor_type="codex",
        entry_type="result",
        content="Committed and push verified.",
        task_id=entry.task_id,
        run_id=run_id,
        metadata={"commit_sha": "a" * 40, "push_verified": True},
    )
    return 0


def run(binding: dict, executor) -> dict:
    return runner.run_once(
        binding["root"],
        binding["thread"],
        binding["repo"],
        binding["state"],
        executor=executor,
    )


def install_binding(
    binding: dict,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    launchctl_exit: int = 0,
) -> tuple[dict, Path, Path]:
    folder = tmp_path / "installed"
    plist = tmp_path / "LaunchAgents" / "runner.plist"
    monkeypatch.setattr(runner.sys, "platform", "darwin")
    monkeypatch.setattr(runner, "paths", lambda *args: (folder, "test.runner", plist))
    monkeypatch.setattr(runner, "_resolved_python", lambda: Path("/usr/local/bin/python3"))
    monkeypatch.setattr(runner.shutil, "which", lambda value: "/usr/local/bin/codex")
    real_run = subprocess.run

    def fake_run(command, *args, **kwargs):
        if command[0] == "/bin/launchctl":
            return subprocess.CompletedProcess(
                command, launchctl_exit, "", "bootstrap failed" if launchctl_exit else ""
            )
        return real_run(command, *args, **kwargs)

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    result = runner.install(
        binding["root"], binding["thread"], binding["repo"], "codex"
    )
    return result, folder / "status.json", plist


def test_unmarked_task_does_not_start(binding: dict) -> None:
    add_task(binding, metadata={})
    calls = []

    result = run(binding, lambda *args: calls.append(args) or 0)

    assert result["status"] == "idle"
    assert calls == []
    assert result["task_count"] == 0


def test_wrong_actor_does_not_start(binding: dict) -> None:
    add_task(binding, actor="Person", actor_type="human")
    calls = []

    result = run(binding, lambda *args: calls.append(args) or 0)

    assert result["status"] == "idle"
    assert calls == []


def test_install_baselines_only_existing_eligible_tasks(
    binding: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    eligible = add_task(binding, task_id="old-eligible")
    add_task(binding, task_id="old-unmarked", metadata={})
    add_task(binding, task_id="old-wrong-actor", actor="Person", actor_type="human")

    installed, state_path, _ = install_binding(binding, tmp_path, monkeypatch)
    calls = []
    visible = runner.status(
        binding["root"], binding["thread"], binding["repo"], state_path
    )
    result = runner.run_once(
        binding["root"],
        binding["thread"],
        binding["repo"],
        state_path,
        executor=lambda *args: calls.append(args) or 0,
    )

    state = json.loads(state_path.read_text())
    assert calls == []
    assert installed["ignored_count"] == 1
    assert visible["ignored_count"] == 1
    assert visible["baseline"]["ignored_count"] == 1
    assert result["ignored_count"] == 1
    assert result["task_statuses"] == {eligible["id"]: "baselined"}
    assert state["baseline"]["newly_ignored_count"] == 1


def test_task_added_after_install_starts_exactly_once(
    binding: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_binding(binding, tmp_path, monkeypatch)
    state_path = tmp_path / "installed" / "status.json"
    task = add_task(binding, task_id="new-after-install")
    calls = []

    def execute(config, entry, run_id):
        calls.append(entry.id)
        return append_claim_and_result(config, entry, run_id)

    first = runner.run_once(
        binding["root"], binding["thread"], binding["repo"], state_path, executor=execute
    )
    second = runner.run_once(
        binding["root"], binding["thread"], binding["repo"], state_path, executor=execute
    )

    assert calls == [task["id"]]
    assert first["task_statuses"] == {task["id"]: "done"}
    assert second["task_statuses"] == {task["id"]: "done"}


def test_restart_keeps_old_task_baselined_and_new_task_done(
    binding: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old = add_task(binding, task_id="old")
    _, state_path, _ = install_binding(binding, tmp_path, monkeypatch)
    new = add_task(binding, task_id="new")
    calls = []

    def execute(config, entry, run_id):
        calls.append(entry.id)
        return append_claim_and_result(config, entry, run_id)

    runner.run_once(
        binding["root"], binding["thread"], binding["repo"], state_path, executor=execute
    )
    restarted = runner.run_once(
        binding["root"], binding["thread"], binding["repo"], state_path, executor=execute
    )

    assert calls == [new["id"]]
    assert restarted["ignored_count"] == 1
    assert restarted["task_statuses"] == {
        old["id"]: "baselined",
        new["id"]: "done",
    }


def test_failed_launchd_bootstrap_rolls_back_new_install_state(
    binding: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    add_task(binding, task_id="old")

    with pytest.raises(RuntimeError, match="launchd registration failed"):
        install_binding(binding, tmp_path, monkeypatch, launchctl_exit=5)

    assert not (tmp_path / "installed" / "status.json").exists()
    assert not (tmp_path / "installed" / "whiteboard_codex_runner.py").exists()
    assert not (tmp_path / "LaunchAgents" / "runner.plist").exists()


def test_marked_task_starts_exactly_once_and_restart_does_not_repeat(binding: dict) -> None:
    task = add_task(binding)
    calls = []

    def execute(config, entry, run_id):
        calls.append((entry.id, run_id))
        return append_claim_and_result(config, entry, run_id)

    first = run(binding, execute)
    second = run(binding, execute)

    assert first["status"] == "done"
    assert first["task_statuses"] == {task["id"]: "done"}
    assert len(calls) == 1
    assert second["task_statuses"] == {task["id"]: "done"}
    assert json.loads(binding["state"].read_text())["tasks"][task["id"]]["status"] == "done"


def test_second_task_added_while_first_is_active_is_not_started_in_same_run(binding: dict) -> None:
    first = add_task(binding, task_id="first")
    calls = []

    def execute(config, entry, run_id):
        calls.append(entry.id)
        add_task(binding, "Second", task_id="second")
        return append_claim_and_result(config, entry, run_id)

    result = run(binding, execute)

    assert calls == [first["id"]]
    assert result["task_count"] == 1
    assert result["active"] is None
    entries = binding["service"].whiteboard(binding["thread"])
    second = [item for item in entries if item.task_id == "second"][0]
    assert second.id not in result["task_statuses"]


def test_shell_metacharacters_are_neither_executed_nor_put_in_bootstrap(binding: dict) -> None:
    marker = binding["repo"] / "should-not-exist"
    payload = f"$(touch {marker}); `touch {marker}`; && touch {marker}"
    task = add_task(binding, payload)
    observed = {}

    def execute(config, entry, run_id):
        observed["command"] = runner.build_command("codex", Path(config["root"]), Path(config["repo"]))
        observed["prompt"] = runner.build_prompt(config, entry, run_id)
        return append_claim_and_result(config, entry, run_id)

    result = run(binding, execute)

    assert result["status"] == "done"
    assert not marker.exists()
    assert payload not in observed["prompt"]
    assert all(payload not in argument for argument in observed["command"])
    assert task["id"] in observed["prompt"]


def test_command_has_fixed_noninteractive_safety_options(binding: dict) -> None:
    command = runner.build_command("/bin/codex", binding["root"], binding["repo"])

    assert command[:5] == [
        "/bin/codex",
        "-a",
        "never",
        "--sandbox",
        "workspace-write",
    ]
    assert command[command.index("--model") + 1] == "gpt-5.6-sol"
    assert 'model_reasoning_effort="high"' in command
    assert "sandbox_workspace_write.network_access=true" in command
    assert "features.multi_agent=false" in command
    assert "danger-full-access" not in command
    assert command[command.index("-C") + 1] == str(binding["repo"])
    assert command[command.index("--add-dir") + 1] == str(binding["root"])
    assert command[-3:] == ["--color", "never", "-"]


def test_model_and_reasoning_are_explicitly_configurable(binding: dict) -> None:
    command = runner.build_command(
        "/bin/codex", binding["root"], binding["repo"], "gpt-5.6-sol", "xhigh"
    )

    assert command[command.index("--model") + 1] == "gpt-5.6-sol"
    assert 'model_reasoning_effort="xhigh"' in command
    with pytest.raises(ValueError, match="reasoning effort"):
        runner.build_command("/bin/codex", binding["root"], binding["repo"], "gpt-5.6-sol", "invalid")


def test_launchd_install_binds_resolved_python_model_and_reasoning(
    binding: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "installed"
    plist = tmp_path / "LaunchAgents" / "runner.plist"
    python = Path("/Applications/Xcode.app/Contents/Developer/usr/bin/python3").resolve()
    monkeypatch.setattr(runner, "paths", lambda *args: (folder, "test.runner", plist))
    monkeypatch.setattr(runner, "_resolved_python", lambda: python)
    monkeypatch.setattr(runner.shutil, "which", lambda value: "/usr/local/bin/codex")

    real_run = subprocess.run

    def fake_run(command, *args, **kwargs):
        if command[0] == "/bin/launchctl":
            return subprocess.CompletedProcess(command, 0, "", "")
        return real_run(command, *args, **kwargs)

    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    result = runner.install(
        binding["root"],
        binding["thread"],
        binding["repo"],
        "codex",
        "gpt-5.6-sol",
        "high",
    )
    launchd = plistlib.loads(plist.read_bytes())
    arguments = launchd["ProgramArguments"]

    assert arguments[0] == str(python)
    assert arguments[arguments.index("--model") + 1] == "gpt-5.6-sol"
    assert arguments[arguments.index("--reasoning-effort") + 1] == "high"
    assert result["python"] == str(python)
    assert result["model"] == "gpt-5.6-sol"
    assert result["reasoning_effort"] == "high"


def test_launchd_install_rejects_python_older_than_39(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner.sys, "version_info", (3, 8, 18))

    with pytest.raises(ValueError, match="Python 3.9 or newer"):
        runner._resolved_python()


def test_missing_repo_and_thread_are_clean_errors(binding: dict) -> None:
    with pytest.raises(ValueError, match="repository does not exist"):
        runner.run_once(
            binding["root"],
            binding["thread"],
            binding["repo"] / "missing",
            binding["state"],
            executor=append_claim_and_result,
        )
    with pytest.raises(Exception, match="Thread nicht gefunden"):
        runner.run_once(
            binding["root"],
            "missing-thread",
            binding["repo"],
            binding["state"],
            executor=append_claim_and_result,
        )


def test_problem_entry_finishes_task_as_blocked(binding: dict) -> None:
    task = add_task(binding)

    def execute(config, entry, run_id):
        store = JsonStore(Path(config["root"]))
        append(
            store,
            entry.thread_id,
            actor="Terminal-Codex",
            actor_type="codex",
            entry_type="claimed",
            content="Claimed.",
            task_id=entry.task_id,
            run_id=run_id,
        )
        append(
            store,
            entry.thread_id,
            actor="Terminal-Codex",
            actor_type="codex",
            entry_type="problem",
            content="A concrete blocker.",
            task_id=entry.task_id,
            run_id=run_id,
        )
        return 0

    result = run(binding, execute)

    assert result["status"] == "blocked"
    assert result["task_statuses"][task["id"]] == "blocked"


@pytest.mark.parametrize(
    "claimed,metadata",
    [
        (False, {"commit_sha": "b" * 40, "push_verified": True}),
        (True, {"commit_sha": "b" * 40, "push_verified": False}),
        (True, {"push_verified": True}),
    ],
)
def test_result_without_full_claim_commit_push_evidence_is_blocked(
    binding: dict, claimed: bool, metadata: dict
) -> None:
    task = add_task(binding)

    def execute(config, entry, run_id):
        store = JsonStore(Path(config["root"]))
        if claimed:
            append(
                store,
                entry.thread_id,
                actor="Terminal-Codex",
                actor_type="codex",
                entry_type="claimed",
                content="Claimed.",
                task_id=entry.task_id,
                run_id=run_id,
            )
        append(
            store,
            entry.thread_id,
            actor="Terminal-Codex",
            actor_type="codex",
            entry_type="result",
            content="Incomplete result proof.",
            task_id=entry.task_id,
            run_id=run_id,
            metadata=metadata,
        )
        return 0

    result = run(binding, execute)

    assert result["status"] == "blocked"
    assert result["task_statuses"][task["id"]] == "blocked"
    assert any(
        item.entry_type == "problem" and item.metadata.get("reason") == "invalid_result_evidence"
        for item in binding["service"].whiteboard(binding["thread"])
    )


def test_standalone_stop_is_persisted_without_start(binding: dict) -> None:
    task = add_task(binding, "Prepare carefully\nSTOP\nDo not continue")
    calls = []

    result = run(binding, lambda *args: calls.append(args) or 0)

    assert calls == []
    assert result["status"] == "stopped"
    assert result["task_statuses"][task["id"]] == "stopped"


def test_branch_change_is_detected_and_cannot_finish_done(binding: dict) -> None:
    task = add_task(binding)

    def execute(config, entry, run_id):
        completed = subprocess.run(
            ["git", "-C", str(binding["repo"]), "switch", "-c", "task-controlled"],
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr
        return append_claim_and_result(config, entry, run_id)

    result = run(binding, execute)

    assert result["status"] == "blocked"
    assert result["task_statuses"][task["id"]] == "blocked"
    assert any(
        item.entry_type == "problem" and item.metadata.get("reason") == "branch_changed"
        for item in binding["service"].whiteboard(binding["thread"])
    )
