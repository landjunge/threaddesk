"""Independent store reopen proves confirmed registry writes survive races."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import sqlite3
import sys
import threading
import time

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.core.errors import InvalidState
from threaddesk.core.models import new_thread
from threaddesk.services.actors import ActorRegistry
from threaddesk.services.commands import CommandApplication
from threaddesk.services.modules import ModuleManifest, ModuleRegistry
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore


STORES = {"json": JsonStore, "sqlite": SQLiteStore}


def _close(store):
    if hasattr(store, "connection"):
        store.connection.close()


def _wait_for(path, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(.02)
    raise TimeoutError(f"Test process did not reach {path.name}")


def _process_write(home, backend, action, suffix, gate_path):
    """Pause only the first reader, never place a barrier inside both writers."""
    gates = Path(gate_path)
    store = STORES[backend](Path(home))
    try:
        original_transaction = store.transaction
        original_artifact_read = store.read_json_artifact

        @contextmanager
        def observed_writer():
            (gates / (suffix + ".writer_attempt")).touch()
            with original_transaction():
                yield

        store.transaction = observed_writer

        def observed_read(name):
            # JSON catalogue reads can already wait on the same held writer
            # before a command reaches its reservation transaction.
            (gates / (suffix + ".writer_attempt")).touch()
            return original_artifact_read(name)

        store.read_json_artifact = observed_read
        if suffix == "first":
            registry_type, reader = ((ModuleRegistry, "_load") if action.startswith("modules.") else (ActorRegistry, "_read"))
            original = getattr(registry_type, reader)

            def paused(self):
                value = original(self)
                (gates / "entered").touch()
                _wait_for(gates / "release")
                return value

            setattr(registry_type, reader, paused)
        (gates / (suffix + ".ready")).touch()
        _wait_for(gates / (suffix + ".start"))
        (gates / (suffix + ".attempting")).touch()
        if action == "actors":
            app = CommandApplication(ThreadService(store))
            result = app.call({"version": 1, "workspace_id": app.workspace_id, "command": "actors.human",
                               "arguments": {"name": suffix, "color_token": "moss"},
                               "operation_id": "actor-" + suffix})["result"]
            value = result["id"]
        elif action == "instance":
            value = ActorRegistry(store).instance_id()
        else:
            registry = ModuleRegistry(store)
            if action == "modules.install":
                value = registry.install(ModuleManifest(id=suffix, name=suffix, version="1")).manifest.id
            elif action == "modules.update":
                value = registry.update(ModuleManifest(id=suffix, name=suffix, version="2")).manifest.id
            elif action == "modules.enable":
                value = registry.set_enabled(suffix, True).manifest.id
            else:
                value = registry.uninstall(suffix).id
        result = {"ok": True, "value": value}
    except BaseException as exc:
        result = {"ok": False, "error": repr(exc)}
    finally:
        _close(store)
    (gates / (suffix + ".result")).write_text(json.dumps(result))


@pytest.mark.parametrize("backend", STORES)
@pytest.mark.parametrize("action", ["actors", "instance", "modules.install", "modules.update", "modules.enable", "modules.uninstall"])
def test_cross_process_registry_writes_wait_for_existing_store_writer(tmp_path, backend, action):
    home = tmp_path / "workspace"
    store = STORES[backend](home)
    if action.startswith("modules.") and action != "modules.install":
        for identity in ("first", "second", "retained"):
            ModuleRegistry(store).install(ModuleManifest(id=identity, name=identity, version="1"))
    _close(store)
    gates = tmp_path / "gates"
    gates.mkdir()
    root = Path(__file__).resolve().parents[1]
    env = {**os.environ, "PYTHONPATH": os.pathsep.join((str(root / "src"), str(root / "tests"))),
           "PYTHONDONTWRITEBYTECODE": "1"}
    workers = [subprocess.Popen([sys.executable, "-c",
                                "import sys; from test_registry_consistency import _process_write; _process_write(*sys.argv[1:])",
                                str(home), backend, action, suffix, str(gates)],
                               cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
               for suffix in ("first", "second")]
    try:
        for suffix in ("first", "second"):
            _wait_for(gates / (suffix + ".ready"))
        (gates / "first.start").touch()
        _wait_for(gates / "entered")
        (gates / "second.start").touch()
        _wait_for(gates / "second.writer_attempt")
        # Before the fix the second write completed here; releasing the stale
        # first reader then silently overwrote that independently confirmed ID.
        time.sleep(.3)
        assert not (gates / "second.result").exists(), "Second writer bypassed the active store writer"
        (gates / "release").touch()
        results = []
        for suffix, worker in zip(("first", "second"), workers):
            output, error = worker.communicate(timeout=15)
            assert worker.returncode == 0, output + error
            results.append(json.loads((gates / (suffix + ".result")).read_text()))
        assert all(result["ok"] for result in results), results
        reopened = STORES[backend](home)
        try:
            if action == "actors":
                assert {result["value"] for result in results} == {actor["id"] for actor in ActorRegistry(reopened).list()}
            elif action == "instance":
                assert results[0]["value"] == results[1]["value"] == ActorRegistry(reopened).existing_instance_id()
            else:
                saved = {item.manifest.id: item for item in ModuleRegistry(reopened).list()}
                expected = {"retained"} if action == "modules.uninstall" else {"first", "second"}
                if action in {"modules.update", "modules.enable"}:
                    expected.add("retained")
                assert set(saved) == expected
                if action == "modules.update":
                    assert saved["first"].manifest.version == saved["second"].manifest.version == "2"
                elif action == "modules.enable":
                    assert saved["first"].enabled and saved["second"].enabled
        finally:
            _close(reopened)
    finally:
        (gates / "release").touch()
        for worker in workers:
            try:
                worker.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                worker.terminate()
                worker.communicate(timeout=5)


def test_other_thread_cannot_join_an_active_json_transaction(tmp_path):
    store = JsonStore(tmp_path)
    first = ActorRegistry(store)
    entered, release = threading.Event(), threading.Event()
    original = first._read

    def paused():
        value = original()
        entered.set()
        assert release.wait(5)
        return value

    first._read = paused
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            one = pool.submit(first.add_human, "First", "moss")
            assert entered.wait(5)
            other = pool.submit(lambda: (store.in_transaction, ActorRegistry(store).add_human("Second", "sea")))
            assert not other.done()
            release.set()
            actors = [one.result(), other.result()[1]]
            assert other.result()[0] is False
    finally:
        release.set()
    assert {actor["id"] for actor in ActorRegistry(JsonStore(tmp_path)).list()} == {actor["id"] for actor in actors}


def test_other_thread_cannot_write_sqlite_artifacts_by_joining_foreign_transaction(tmp_path):
    store = SQLiteStore(tmp_path)

    def foreign_writer():
        assert not store.in_transaction
        ActorRegistry(store).add_human("Foreign thread", "sea")

    try:
        with ThreadPoolExecutor(max_workers=1) as pool, store.transaction():
            future = pool.submit(foreign_writer)
            with pytest.raises(RuntimeError, match="another thread"):
                future.result(timeout=5)
            assert ActorRegistry(store).list() == []
        kept = ActorRegistry(store).add_human("Owning thread", "moss")
        reopened = SQLiteStore(tmp_path)
        try:
            assert {actor["id"] for actor in ActorRegistry(reopened).list()} == {kept["id"]}
        finally:
            _close(reopened)
    finally:
        _close(store)


def test_busy_sqlite_begin_does_not_leave_a_joinable_transaction(tmp_path):
    blocker, waiting = SQLiteStore(tmp_path), SQLiteStore(tmp_path)
    waiting.connection.execute("PRAGMA busy_timeout=1")
    try:
        with blocker.transaction():
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                ActorRegistry(waiting).add_human("Must not write", "sea")
            assert not waiting.in_transaction
            assert not waiting.connection.in_transaction
            assert ActorRegistry(waiting).list() == []
        kept = ActorRegistry(waiting).add_human("After lock release", "moss")
        reopened = SQLiteStore(tmp_path)
        try:
            assert {actor["id"] for actor in ActorRegistry(reopened).list()} == {kept["id"]}
        finally:
            _close(reopened)
    finally:
        _close(blocker)
        _close(waiting)


@pytest.mark.parametrize("backend", STORES)
@pytest.mark.parametrize("artifact", ["actors.json", "modules.json"])
def test_null_registry_is_not_missing_and_is_preserved(tmp_path, backend, artifact):
    store = STORES[backend](tmp_path)
    path = store.artifact_path(artifact)
    path.write_text("null\n")
    try:
        with pytest.raises(InvalidState, match="artifact_json_object"):
            if artifact == "actors.json":
                ActorRegistry(store).add_human("Must not overwrite", "moss")
            else:
                ModuleRegistry(store).install(ModuleManifest(id="example", name="Example", version="1"))
        assert path.read_text() == "null\n"
    finally:
        _close(store)


@pytest.mark.parametrize("backend", STORES)
def test_registry_writers_reuse_transaction_and_read_their_pending_changes(tmp_path, backend):
    store = STORES[backend](tmp_path)
    registry = ModuleRegistry(store)
    people = ActorRegistry(store)
    try:
        with store.transaction():
            assert store.in_transaction
            human = people.add_human("First", "moss")
            agent = people.add_agent("Assistant", human["id"], "local-assistant")
            people.rename(human["id"], "Renamed")
            people.recolor(human["id"], "sea")
            assert people.get(human["id"])["name"] == "Renamed"
            assert people.get(agent["id"])["person_id"] == human["id"]
            registry.install(ModuleManifest(id="alpha", name="Alpha", version="1"))
            registry.install(ModuleManifest(id="beta", name="Beta", version="1"))
            assert registry.set_enabled("alpha", True).enabled
            assert registry.update(ModuleManifest(id="alpha", name="Alpha", version="2")).enabled
            registry.uninstall("beta")
            assert [item.manifest.id for item in registry.list()] == ["alpha"]
        assert not store.in_transaction
        reopened = STORES[backend](tmp_path)
        try:
            assert len(ActorRegistry(reopened).list()) == 2
            assert ModuleRegistry(reopened).get("alpha").manifest.version == "2"
            assert ModuleRegistry(reopened).get("alpha").enabled
            assert not (tmp_path / "modules.lock").exists()
        finally:
            _close(reopened)
    finally:
        _close(store)


@pytest.mark.parametrize("backend", STORES)
def test_artifact_rollback_boundary_is_explicit(tmp_path, backend):
    store = STORES[backend](tmp_path)
    try:
        with pytest.raises(RuntimeError, match="rollback"):
            with store.transaction():
                store.save_thread(new_thread("SQL/domain write rolls back"))
                ActorRegistry(store).add_human("Artifact", "ink")
                ModuleRegistry(store).install(ModuleManifest(id="example", name="Example", version="1"))
                raise RuntimeError("rollback")
        reopened = STORES[backend](tmp_path)
        try:
            assert reopened.list_threads() == []
            # SQLite artifacts remain external files, not part of SQL rollback.
            expected = 0 if backend == "json" else 1
            assert len(ActorRegistry(reopened).list()) == expected
            assert len(ModuleRegistry(reopened).list()) == expected
            assert not reopened.in_transaction
        finally:
            _close(reopened)
    finally:
        _close(store)
