#!/usr/bin/env python3
"""Run one explicitly authorized Whiteboard task with one bound Codex process.

The runner is intentionally small: one Whiteboard thread, one Git repository and
at most one active task.  Whiteboard writes always use the ThreadDesk service.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
if SOURCE_ROOT.is_dir() and str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from threaddesk.services.whiteboard import append, list_entries  # noqa: E402
from threaddesk.storage.json_store import JsonStore  # noqa: E402


RUNNER_VERSION = 1
RUNNER_MARKER = "codex-v1"
DEFAULT_MODEL = "gpt-5.6-sol"
DEFAULT_REASONING_EFFORT = "high"
REASONING_EFFORTS = {"low", "medium", "high", "xhigh", "max", "ultra"}
FEEDBACK_SECONDS = 60
TERMINAL_GRACE_SECONDS = 30
TERMINAL_TYPES = {"result", "problem"}
Executor = Callable[[dict[str, Any], Any, str], int]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def _binding_key(thread_id: str, repo: Path) -> str:
    digest = hashlib.sha256(str(repo.resolve()).encode("utf-8")).hexdigest()[:12]
    return f"{thread_id}-{digest}"


def paths(thread_id: str, repo: Path) -> tuple[Path, str, Path]:
    key = _binding_key(thread_id, repo)
    folder = (
        Path.home()
        / "Library"
        / "Application Support"
        / "ThreadDesk"
        / "whiteboard-codex-runner"
        / key
    )
    label = "de.netzwerkpunkt.threaddesk.whiteboard-codex." + key
    plist = Path.home() / "Library" / "LaunchAgents" / (label + ".plist")
    return folder, label, plist


def _validate_codex_settings(model: str, reasoning_effort: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", model):
        raise ValueError("Codex model must be a non-empty model identifier")
    if reasoning_effort not in REASONING_EFFORTS:
        allowed = ", ".join(sorted(REASONING_EFFORTS))
        raise ValueError(f"Unsupported Codex reasoning effort: {reasoning_effort}; choose {allowed}")


def _identity(
    root: Path,
    thread_id: str,
    repo: Path,
    model: str = DEFAULT_MODEL,
    reasoning_effort: str = DEFAULT_REASONING_EFFORT,
) -> dict[str, Any]:
    return {
        "runner_version": RUNNER_VERSION,
        "root": str(root.resolve()),
        "thread_id": thread_id,
        "repo": str(repo.resolve()),
        "model": model,
        "reasoning_effort": reasoning_effort,
    }


def _load_state(path: Path, identity: dict[str, Any]) -> dict[str, Any]:
    if path.exists():
        state = json.loads(path.read_text(encoding="utf-8"))
        if any(state.get(key) != value for key, value in identity.items()):
            raise ValueError("State belongs to another runner binding")
    else:
        state = dict(identity)
        state.update(status="idle", active=None, tasks={})
    if not isinstance(state.get("tasks"), dict):
        raise ValueError("Runner state has an invalid task registry")
    return state


def _validate(root: Path, thread_id: str, repo: Path) -> tuple[JsonStore, Path, Path]:
    root = root.expanduser().resolve()
    repo = repo.expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Whiteboard root does not exist: {root}")
    store = JsonStore(root)
    store.get_thread(thread_id)
    if not repo.is_dir():
        raise ValueError(f"Bound repository does not exist: {repo}")
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if result.returncode or Path(result.stdout.strip()).resolve() != repo:
        raise ValueError(f"Bound path is not a Git repository root: {repo}")
    return store, root, repo


def _current_branch(repo: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), "symbolic-ref", "--quiet", "--short", "HEAD"],
        capture_output=True,
        text=True,
    )
    branch = result.stdout.strip()
    if result.returncode or not branch:
        raise ValueError(f"Bound repository must be on a named branch: {repo}")
    return branch


def _eligible(entry: Any) -> bool:
    return (
        entry.entry_type == "task"
        and entry.actor_type == "chatgpt"
        and entry.metadata.get("runner") == RUNNER_MARKER
    )


def _contains_stop(entry: Any) -> bool:
    return any(line.strip().upper() == "STOP" for line in entry.content.splitlines())


def _new_run_id(entry_id: str) -> str:
    return f"codex-{entry_id}-{uuid4().hex[:12]}"


def build_command(
    codex_bin: str,
    root: Path,
    repo: Path,
    model: str = DEFAULT_MODEL,
    reasoning_effort: str = DEFAULT_REASONING_EFFORT,
) -> list[str]:
    """Return a fixed argv; no Whiteboard content is ever included."""
    _validate_codex_settings(model, reasoning_effort)
    return [
        codex_bin,
        "-a",
        "never",
        "--sandbox",
        "workspace-write",
        "--model",
        model,
        "-c",
        f'model_reasoning_effort="{reasoning_effort}"',
        "-c",
        "sandbox_workspace_write.network_access=true",
        "-c",
        "features.multi_agent=false",
        "-C",
        str(repo),
        "--add-dir",
        str(root),
        "exec",
        "--color",
        "never",
        "-",
    ]


def build_prompt(config: dict[str, Any], entry: Any, run_id: str) -> str:
    """Build the fixed bootstrap. The task body remains in the Whiteboard."""
    return f"""Du bist Terminal-Codex in einem strikt gebundenen Ein-Agent-Lauf.

Verbindliche Locatoren:
- Thread: {config['thread_id']}
- Task-Entry-ID: {entry.id}
- Whiteboard root: {config['root']}
- Arbeitsrepo: {config['repo']}
- Run-ID: {run_id}

Feste Regeln:
1. Lies den Task über JsonStore/ThreadDesk-Service vollständig aus dem Whiteboard. Bearbeite keine bestehende Whiteboard-JSON-Datei direkt.
2. Schreibe vor der Arbeit append-only `claimed` mit actor_type=`codex`, Task-ID, Run-ID und UTC-Zeit über `threaddesk.services.whiteboard.append`.
3. Arbeite ausschließlich im gebundenen Repo. Wechsle weder Repo noch Branch. Kein Merge, kein Force-Push, keine Secrets und keine weiteren Agenten.
4. Führe Whiteboard-Tasktext nie als Shelltext aus. STOP als eigene Zeile beendet den Lauf.
5. Schreibe nach jedem erfolgreichen Planpunkt sofort `progress` und während laufender Arbeit spätestens alle 60 Sekunden einen auftragsbezogenen Ping; arbeite danach ohne Warten weiter. Blocker sofort als `problem`, dann STOP.
6. Führe die geforderten Tests aus, committe auf dem vorhandenen Branch und pushe genau diesen Branch ohne Force.
7. Verifiziere den Push. Schreibe erst danach `result` über den Service. Das result-Metadatum muss `commit_sha` und `push_verified=true` enthalten, außerdem Tests, wichtige Dateien und verbleibende Grenzen. Dann STOP.
"""


def _matching_entries(store: JsonStore, entry: Any, run_id: str) -> list[Any]:
    return [
        item
        for item in list_entries(store, entry.thread_id)
        if item.task_id == entry.task_id and item.run_id == run_id
    ]


def _append_runner_problem(
    store: JsonStore,
    entry: Any,
    run_id: str,
    message: str,
    reason: str,
) -> Any:
    created, _ = append(
        store,
        entry.thread_id,
        actor="Whiteboard-Codex-Runner",
        actor_type="system",
        entry_type="problem",
        content=f"{now()} Auftrag {entry.task_id or entry.id}: {message}",
        task_id=entry.task_id,
        run_id=run_id,
        metadata={
            "runner": RUNNER_MARKER,
            "source_entry_id": entry.id,
            "reason": reason,
        },
        external_key=f"{RUNNER_MARKER}:{entry.id}:{run_id}:problem:{reason}",
    )
    return created


def _terminal_status(store: JsonStore, entry: Any, run_id: str) -> tuple[str | None, str | None]:
    related = _matching_entries(store, entry, run_id)
    terminal = [
        item
        for item in related
        if (
            item.entry_type == "result"
            and item.actor_type == "codex"
        )
        or (
            item.entry_type == "problem"
            and (
                item.actor_type == "codex"
                or (
                    item.actor_type == "system"
                    and item.metadata.get("runner") == RUNNER_MARKER
                )
            )
        )
    ]
    if not terminal:
        return None, None
    last = terminal[-1]
    if last.entry_type == "problem":
        return "blocked", last.id
    claimed = any(
        item.entry_type == "claimed" and item.actor_type == "codex" for item in related
    )
    commit_sha = last.metadata.get("commit_sha")
    push_verified = last.metadata.get("push_verified") is True
    if (
        claimed
        and isinstance(commit_sha, str)
        and re.fullmatch(r"[0-9a-fA-F]{7,40}", commit_sha)
        and push_verified
    ):
        return "done", last.id
    return "invalid_result", last.id


def _process_alive(pid: Any) -> bool:
    if not isinstance(pid, int) or pid < 1:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _terminate(process: subprocess.Popen[Any]) -> None:
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _run_codex(config: dict[str, Any], entry: Any, run_id: str) -> int:
    store = JsonStore(Path(config["root"]))
    state_path = Path(config["state_path"])
    log_path = state_path.parent / f"{run_id}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    command = build_command(
        config["codex_bin"],
        Path(config["root"]),
        Path(config["repo"]),
        config["model"],
        config["reasoning_effort"],
    )
    environment = dict(os.environ)
    source = environment.get("THREADDESK_SOURCE_ROOT", str(SOURCE_ROOT))
    current_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = source + (os.pathsep + current_pythonpath if current_pythonpath else "")
    with log_path.open("w", encoding="utf-8") as log:
        os.chmod(log_path, 0o600)
        process = subprocess.Popen(
            command,
            cwd=config["repo"],
            env=environment,
            stdin=subprocess.PIPE,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
        )
        config["on_pid"](process.pid, str(log_path))
        assert process.stdin is not None
        process.stdin.write(build_prompt(config, entry, run_id))
        process.stdin.close()
        seen_ids: set[str] = set()
        last_ping = time.monotonic()
        terminal_since: float | None = None
        while process.poll() is None:
            related = _matching_entries(store, entry, run_id)
            current_ids = {
                item.id
                for item in related
                if item.actor_type == "codex"
                and item.entry_type in {"claimed", "progress", "problem", "result"}
            }
            if current_ids - seen_ids:
                seen_ids = current_ids
                last_ping = time.monotonic()
            terminal_status, _ = _terminal_status(store, entry, run_id)
            if terminal_status is not None:
                terminal_since = terminal_since or time.monotonic()
                if time.monotonic() - terminal_since >= TERMINAL_GRACE_SECONDS:
                    _terminate(process)
                    return 125
            elif time.monotonic() - last_ping >= FEEDBACK_SECONDS:
                _append_runner_problem(
                    store,
                    entry,
                    run_id,
                    "Kein auftragsbezogener Codex-Ping innerhalb von 60 Sekunden; Lauf fail-closed beendet. Der Timer weckt keine Voice-Sitzung.",
                    "feedback_timeout",
                )
                _terminate(process)
                return 124
            time.sleep(1)
        return int(process.returncode or 0)


def _finish_task(
    store: JsonStore,
    state: dict[str, Any],
    state_path: Path,
    entry: Any,
    run_id: str,
    exit_code: int,
) -> dict[str, Any]:
    status, evidence_id = _terminal_status(store, entry, run_id)
    if status == "invalid_result":
        problem = _append_runner_problem(
            store,
            entry,
            run_id,
            "Result ohne vorheriges Codex-Claim oder ohne strukturierten Commit-/Push-Beleg; Lauf nicht als erfolgreich gewertet.",
            "invalid_result_evidence",
        )
        status, evidence_id = "blocked", problem.id
    elif status is None:
        problem = _append_runner_problem(
            store,
            entry,
            run_id,
            f"Codex-Prozess endete mit Exit {exit_code}, aber ohne result/problem im Whiteboard.",
            "missing_terminal_entry",
        )
        status, evidence_id = "blocked", problem.id
    record = state["tasks"][entry.id]
    record.update(
        status=status,
        finished_at=now(),
        exit_code=exit_code,
        evidence_entry_id=evidence_id,
    )
    state.update(status=status, active=None, last_attempt_at=now(), last_task_id=entry.id)
    atomic_json(state_path, state)
    return _public_state(state)


def _public_state(state: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in state.items() if key != "tasks"} | {
        "task_count": len(state.get("tasks", {})),
        "task_statuses": {
            key: value.get("status") for key, value in state.get("tasks", {}).items()
        },
    }


def run_once(
    root: Path,
    thread_id: str,
    repo: Path,
    state_path: Path,
    codex_bin: str = "codex",
    model: str = DEFAULT_MODEL,
    reasoning_effort: str = DEFAULT_REASONING_EFFORT,
    executor: Executor | None = None,
) -> dict[str, Any]:
    store, root, repo = _validate(root, thread_id, repo)
    bound_branch = _current_branch(repo)
    _validate_codex_settings(model, reasoning_effort)
    if executor is None and shutil.which(codex_bin) is None:
        raise ValueError(f"Codex executable not found: {codex_bin}")
    identity = _identity(root, thread_id, repo, model, reasoning_effort)
    state_path = state_path.expanduser().resolve()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = state_path.with_suffix(state_path.suffix + ".lock")
    with lock_path.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {**identity, "status": "busy", "active": None}
        state = _load_state(state_path, identity)
        entries = list_entries(store, thread_id)
        by_id = {item.id: item for item in entries}
        active = state.get("active")
        if isinstance(active, dict):
            active_entry = by_id.get(active.get("entry_id"))
            if active_entry is None:
                raise ValueError("Active task entry disappeared from the append-only Whiteboard")
            terminal, evidence_id = _terminal_status(store, active_entry, active["run_id"])
            if terminal == "done" or terminal == "blocked":
                record = state["tasks"][active_entry.id]
                record.update(status=terminal, finished_at=now(), evidence_entry_id=evidence_id)
                state.update(status=terminal, active=None, last_attempt_at=now())
                atomic_json(state_path, state)
            elif _process_alive(active.get("pid")):
                state.update(status="running", last_attempt_at=now())
                atomic_json(state_path, state)
                return _public_state(state)
            else:
                problem = _append_runner_problem(
                    store,
                    active_entry,
                    active["run_id"],
                    "Runner-Neustart fand einen unvollständigen Lauf ohne aktiven Prozess; Aufgabe wird nicht erneut gestartet.",
                    "interrupted_run",
                )
                state["tasks"][active_entry.id].update(
                    status="blocked", finished_at=now(), evidence_entry_id=problem.id
                )
                state.update(status="blocked", active=None, last_attempt_at=now())
                atomic_json(state_path, state)

        candidates = [
            item
            for item in entries
            if _eligible(item) and item.id not in state["tasks"]
        ]
        if not candidates:
            if state["tasks"]:
                last = state["tasks"].get(state.get("last_task_id"), {})
                resting_status = last.get("status", "idle")
            else:
                resting_status = "idle"
            state.update(status=resting_status, active=None, last_attempt_at=now())
            atomic_json(state_path, state)
            return _public_state(state)
        entry = candidates[0]
        run_id = _new_run_id(entry.id)
        if not entry.task_id:
            problem = _append_runner_problem(
                store, entry, run_id, "Markierter Task hat keine task_id und wird nicht gestartet.", "missing_task_id"
            )
            state["tasks"][entry.id] = {
                "status": "blocked",
                "run_id": run_id,
                "finished_at": now(),
                "evidence_entry_id": problem.id,
            }
            state.update(status="blocked", last_attempt_at=now(), last_task_id=entry.id)
            atomic_json(state_path, state)
            return _public_state(state)
        if _contains_stop(entry):
            problem = _append_runner_problem(
                store, entry, run_id, "STOP im Task erkannt; Codex wurde nicht gestartet.", "task_stop"
            )
            state["tasks"][entry.id] = {
                "status": "stopped",
                "run_id": run_id,
                "finished_at": now(),
                "evidence_entry_id": problem.id,
            }
            state.update(status="stopped", last_attempt_at=now(), last_task_id=entry.id)
            atomic_json(state_path, state)
            return _public_state(state)

        started = now()
        state["tasks"][entry.id] = {
            "status": "running",
            "task_id": entry.task_id,
            "run_id": run_id,
            "started_at": started,
            "pid": None,
        }
        state["active"] = {
            "entry_id": entry.id,
            "task_id": entry.task_id,
            "run_id": run_id,
            "started_at": started,
            "pid": None,
        }
        state.update(status="running", last_attempt_at=started, last_task_id=entry.id)
        atomic_json(state_path, state)

        def on_pid(pid: int, log_path: str) -> None:
            state["active"].update(pid=pid, log_path=log_path)
            state["tasks"][entry.id].update(pid=pid, log_path=log_path)
            atomic_json(state_path, state)

        config = {
            **identity,
            "branch": bound_branch,
            "state_path": str(state_path),
            "codex_bin": codex_bin,
            "model": model,
            "reasoning_effort": reasoning_effort,
            "on_pid": on_pid,
        }
        chosen_executor = executor or _run_codex
        try:
            exit_code = chosen_executor(config, entry, run_id)
        except Exception as exc:  # preserve a visible terminal record for runner failures
            _append_runner_problem(
                store,
                entry,
                run_id,
                f"Runner konnte Codex nicht ausführen: {type(exc).__name__}: {exc}",
                "runner_exception",
            )
            exit_code = 126
        try:
            branch_after = _current_branch(repo)
        except ValueError:
            branch_after = "(detached)"
        if branch_after != bound_branch:
            _append_runner_problem(
                store,
                entry,
                run_id,
                f"Gebundener Branch wurde verändert ({bound_branch} -> {branch_after}); Lauf nicht als erfolgreich gewertet.",
                "branch_changed",
            )
        return _finish_task(store, state, state_path, entry, run_id, int(exit_code))


def status(
    root: Path,
    thread_id: str,
    repo: Path,
    state_path: Path,
    model: str = DEFAULT_MODEL,
    reasoning_effort: str = DEFAULT_REASONING_EFFORT,
) -> dict[str, Any]:
    _, root, repo = _validate(root, thread_id, repo)
    _validate_codex_settings(model, reasoning_effort)
    identity = _identity(root, thread_id, repo, model, reasoning_effort)
    if not state_path.exists():
        return {**identity, "status": "not_started", "active": None, "task_count": 0, "task_statuses": {}}
    return _public_state(_load_state(state_path, identity))


def _resolved_python() -> Path:
    if sys.version_info < (3, 9):
        version = ".".join(str(part) for part in sys.version_info[:3])
        raise ValueError(
            f"Python 3.9 or newer is required for launchd installation; installer is running under {version}"
        )
    try:
        executable = Path(sys.executable).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValueError(f"Cannot resolve the current Python interpreter: {sys.executable}") from exc
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise ValueError(f"Current Python interpreter is not executable: {executable}")
    return executable


def install(
    root: Path,
    thread_id: str,
    repo: Path,
    codex_bin: str,
    model: str = DEFAULT_MODEL,
    reasoning_effort: str = DEFAULT_REASONING_EFFORT,
) -> dict[str, Any]:
    if sys.platform != "darwin":
        raise ValueError("Installation requires macOS launchd")
    python_executable = _resolved_python()
    _validate_codex_settings(model, reasoning_effort)
    _, root, repo = _validate(root, thread_id, repo)
    _current_branch(repo)
    executable = shutil.which(codex_bin)
    if executable is None:
        raise ValueError(f"Codex executable not found: {codex_bin}")
    folder, label, plist = paths(thread_id, repo)
    if plist.exists():
        raise ValueError("Runner already installed; inspect status or uninstall first")
    folder.mkdir(parents=True, exist_ok=True)
    os.chmod(folder, 0o700)
    script = folder / "whiteboard_codex_runner.py"
    shutil.copy2(Path(__file__).resolve(), script)
    state_path = folder / "status.json"
    program = [
        str(python_executable),
        str(script),
        "once",
        "--root",
        str(root),
        "--thread",
        thread_id,
        "--repo",
        str(repo),
        "--state",
        str(state_path),
        "--codex",
        executable,
        "--model",
        model,
        "--reasoning-effort",
        reasoning_effort,
    ]
    config = {
        "Label": label,
        "ProgramArguments": program,
        "EnvironmentVariables": {
            "PYTHONPATH": str(SOURCE_ROOT),
            "THREADDESK_SOURCE_ROOT": str(SOURCE_ROOT),
        },
        "StartInterval": 15,
        "RunAtLoad": True,
        "ProcessType": "Background",
        "Umask": 63,
        "StandardOutPath": str(folder / "launchd.stdout.log"),
        "StandardErrorPath": str(folder / "launchd.stderr.log"),
    }
    plist.parent.mkdir(parents=True, exist_ok=True)
    with plist.open("xb") as stream:
        plistlib.dump(config, stream)
    os.chmod(plist, 0o600)
    result = subprocess.run(
        ["/bin/launchctl", "bootstrap", f"gui/{os.getuid()}", str(plist)],
        capture_output=True,
        text=True,
    )
    if result.returncode:
        plist.unlink()
        raise RuntimeError("launchd registration failed: " + result.stderr.strip())
    return {
        "installed": True,
        "label": label,
        "root": str(root),
        "thread_id": thread_id,
        "repo": str(repo),
        "state_path": str(state_path),
        "python": str(python_executable),
        "model": model,
        "reasoning_effort": reasoning_effort,
        "interval_seconds": 15,
        "feedback_seconds": FEEDBACK_SECONDS,
    }


def uninstall(thread_id: str, repo: Path) -> dict[str, Any]:
    folder, label, plist = paths(thread_id, repo)
    target = f"gui/{os.getuid()}/{label}"
    registered = subprocess.run(
        ["/bin/launchctl", "print", target], capture_output=True
    ).returncode == 0
    if registered:
        subprocess.run(["/bin/launchctl", "bootout", target], check=True)
    if plist.exists():
        plist.unlink()
    return {"installed": False, "state_preserved": str(folder / "status.json")}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["once", "status", "install", "uninstall"])
    parser.add_argument("--root", type=Path, default=Path.home() / ".threaddesk")
    parser.add_argument("--thread", required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--codex", default="codex")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--reasoning-effort", default=DEFAULT_REASONING_EFFORT)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", args.thread):
        parser.error("Invalid thread ID")
    folder, _, _ = paths(args.thread, args.repo)
    state_path = (args.state or folder / "status.json").expanduser().resolve()
    try:
        if args.action == "install":
            result = install(
                args.root,
                args.thread,
                args.repo,
                args.codex,
                args.model,
                args.reasoning_effort,
            )
        elif args.action == "uninstall":
            result = uninstall(args.thread, args.repo)
        elif args.action == "status":
            result = status(
                args.root,
                args.thread,
                args.repo,
                state_path,
                args.model,
                args.reasoning_effort,
            )
        else:
            result = run_once(
                args.root,
                args.thread,
                args.repo,
                state_path,
                args.codex,
                args.model,
                args.reasoning_effort,
            )
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if result.get("status") in {"blocked", "error"} else 0


if __name__ == "__main__":
    sys.exit(main())
