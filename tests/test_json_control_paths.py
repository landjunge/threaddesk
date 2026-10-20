"""The JSON transaction's hidden control files are part of its I/O boundary."""

import json
import os
from pathlib import Path
import pytest

from threaddesk.core.errors import InvalidState
from threaddesk.storage.json_store import JsonStore


@pytest.mark.parametrize("control", [".management.lock", ".management-commit.json"])
def test_external_control_symlink_is_never_read_or_modified(tmp_path, control):
    store = JsonStore(tmp_path / "source")
    outside = tmp_path / "external"
    content = b"" if control.endswith("lock") else b'{"version":1,"writes":{}}'
    outside.write_bytes(content)
    selected = store.root / control
    selected.unlink(missing_ok=True)
    selected.symlink_to(outside)
    with pytest.raises(InvalidState):
        with store.transaction():
            pass
    assert selected.is_symlink()
    assert outside.read_bytes() == content


def test_lock_hardlink_cannot_write_external_file(tmp_path):
    store = JsonStore(tmp_path / "source")
    outside = tmp_path / "external"
    outside.write_bytes(b"")
    lock = store.root / ".management.lock"
    lock.unlink()
    os.link(outside, lock)
    with pytest.raises(InvalidState):
        with store.transaction():
            pass
    assert outside.read_bytes() == b""


def test_journal_hardlink_is_rejected_before_read_and_preserved(tmp_path, monkeypatch):
    store = JsonStore(tmp_path / "source")
    outside = tmp_path / "external"
    body = b'{"version":1,"writes":{}}'
    outside.write_bytes(body)
    os.link(outside, store._journal)
    from threaddesk.storage import workspace_backup
    from threaddesk.storage.windows_backup_source import WindowsSourceTree
    reader = WindowsSourceTree if os.name == "nt" else workspace_backup._SourceTree
    original, reads = reader.read, []

    def traced(self, relative, *args, **kwargs):
        if relative == ".management-commit.json":
            reads.append(relative)
        return original(self, relative, *args, **kwargs)

    monkeypatch.setattr(reader, "read", traced)
    with pytest.raises(InvalidState), store.transaction():
        pass
    assert not reads
    assert store._journal.read_bytes() == outside.read_bytes() == body


def test_normal_wal_replay_never_follows_data_temporary_symlink(tmp_path):
    store = JsonStore(tmp_path / "source")
    outside = tmp_path / "external"
    outside.write_bytes(b"preserve")
    temporary = store.root / "normal.json.tmp"
    temporary.symlink_to(outside)
    with store.transaction():
        store._write_json(store.root / "normal.json", {"synthetic": True})
    assert outside.read_bytes() == b"preserve"
    assert temporary.is_symlink()
    assert not (store.root / "normal.json").is_symlink()
    assert json.loads((store.root / "normal.json").read_text()) == {"synthetic": True}


@pytest.mark.parametrize("operation", ["write", "delete"])
def test_root_swapped_after_journal_read_never_writes_or_deletes_external(tmp_path, monkeypatch, operation):
    from threaddesk.storage import workspace_backup
    from threaddesk.storage.windows_backup_source import WindowsSourceTree
    store = JsonStore(tmp_path / "source")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "recovery.json").write_bytes(b"preserve")
    plan = {"version": 1, "writes": {"recovery.json": None if operation == "delete" else {"synthetic": True}}}
    body = json.dumps(plan)
    store._journal.write_text(body)
    reader = WindowsSourceTree if os.name == "nt" else workspace_backup._SourceTree
    original = reader.read
    attempted = False

    def after_read(self, relative, expected, **kwargs):
        nonlocal attempted
        result = original(self, relative, expected, **kwargs)
        if relative == ".management-commit.json":
            attempted = True
            # On Windows the retained root prevents this rename; POSIX must
            # detect the exchange and never use the new pathname for recovery.
            store.root.rename(tmp_path / "old-root")
            store.root.symlink_to(outside, target_is_directory=True)
        return result

    monkeypatch.setattr(reader, "read", after_read)
    with pytest.raises(InvalidState), store.transaction():
        pass
    assert attempted
    assert (outside / "recovery.json").read_bytes() == b"preserve"
    journal = (tmp_path / "old-root" if os.name != "nt" else store.root) / ".management-commit.json"
    assert journal.read_text() == body


def test_recovery_uses_pinned_nested_parents_for_write_delete_and_creation(tmp_path):
    store = JsonStore(tmp_path / "source")
    selected = store.root / "existing" / "gone.json"
    selected.parent.mkdir()
    selected.write_text("remove")
    plan = {"version": 1, "writes": {"existing/gone.json": None,
                                     "new/nested/file.json": {"saved": True},
                                     "missing/already-gone.json": None}}
    if os.name == "nt":
        plan["writes"] = {str(Path(name)): value for name, value in plan["writes"].items()}
    store._journal.write_text(json.dumps(plan))
    with store.transaction():
        pass
    assert not selected.exists()
    assert json.loads((store.root / "new/nested/file.json").read_text()) == {"saved": True}
    assert not store._journal.exists()


@pytest.mark.parametrize("operation", ["write", "delete"])
def test_recovery_parent_swapped_before_child_open_cannot_touch_external(tmp_path, monkeypatch, operation):
    store = JsonStore(tmp_path / "source")
    parent, outside = store.root / "existing", tmp_path / "outside"
    parent.mkdir()
    outside.mkdir()
    (outside / "recovery.json").write_bytes(b"preserve")
    relative = str(Path("existing") / "recovery.json")
    store._journal.write_text(json.dumps({"version": 1, "writes": {
        relative: None if operation == "delete" else {"synthetic": True}}}))
    changed = False

    def exchange():
        nonlocal changed
        changed = True
        parent.rename(store.root / "old-parent")
        parent.symlink_to(outside, target_is_directory=True)

    if os.name == "nt":
        from threaddesk.storage.windows_backup_source import _WindowsAPI
        original = _WindowsAPI._child

        def before(self, parent_handle, name, **kwargs):
            if name == "existing" and kwargs.get("directory") and not changed:
                exchange()
            return original(self, parent_handle, name, **kwargs)

        monkeypatch.setattr(_WindowsAPI, "_child", before)
    else:
        original = os.open

        def before(name, flags, *args, **kwargs):
            if name == "existing" and flags & os.O_DIRECTORY and not changed:
                exchange()
            return original(name, flags, *args, **kwargs)

        monkeypatch.setattr(os, "open", before)
    with pytest.raises(InvalidState), store.transaction():
        pass
    assert changed
    assert (outside / "recovery.json").read_bytes() == b"preserve"
    assert store._journal.is_file()


def test_normal_transaction_reopens_and_recovers_durable_journal(tmp_path, monkeypatch):
    store = JsonStore(tmp_path / "source")
    original = store._atomic_json
    calls = 0

    def interrupted(path, data):
        nonlocal calls
        original(path, data)
        calls += 1
        if calls == 2:
            raise OSError("synthetic power interruption")

    monkeypatch.setattr(store, "_atomic_json", interrupted)
    with pytest.raises((OSError, InvalidState)):
        with store.transaction():
            store._write_json(store.root / "one.json", {"value": 1})
            store._write_json(store.root / "two.json", {"value": 2})
    assert store._journal.is_file()
    reopened = JsonStore(store.root)
    assert json.loads((reopened.root / "one.json").read_text()) == {"value": 1}
    assert json.loads((reopened.root / "two.json").read_text()) == {"value": 2}
    assert not reopened._journal.exists()
    with reopened.transaction():
        reopened._write_json(reopened.root / "three.json", {"value": 3})
    assert json.loads((reopened.root / "three.json").read_text()) == {"value": 3}


def test_old_fixed_journal_temporary_symlink_never_changes_external_data(tmp_path):
    store = JsonStore(tmp_path / "source")
    outside = tmp_path / "external"
    outside.write_bytes(b"preserve")
    old_temporary = store.root / ".management-commit.json.tmp"
    old_temporary.symlink_to(outside)
    with store.transaction():
        store._write_json(store.root / "normal.json", {"saved": True})
    assert json.loads((store.root / "normal.json").read_text()) == {"saved": True}
    assert outside.read_bytes() == b"preserve"
    assert old_temporary.is_symlink()
    assert not store._journal.exists()


def test_random_journal_temporary_collision_never_opens_or_deletes_foreign_file(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import threaddesk.storage.json_store as module
    import threaddesk.storage.windows_backup_source as windows
    store = JsonStore(tmp_path / "source")
    fixed = SimpleNamespace(hex="f" * 32)
    monkeypatch.setattr(module, "uuid4", lambda: fixed)
    monkeypatch.setattr(windows, "uuid4", lambda: fixed)
    outside = tmp_path / "external"
    outside.write_bytes(b"preserve")
    occupied = store.root / (".management-commit-" + fixed.hex + ".tmp")
    occupied.symlink_to(outside)
    with pytest.raises(InvalidState):
        with store.transaction():
            store._write_json(store.root / "normal.json", {"saved": False})
    assert outside.read_bytes() == b"preserve"
    assert occupied.is_symlink()
    assert not (store.root / "normal.json").exists()


def test_failed_journal_publish_removes_only_its_own_temporary(tmp_path, monkeypatch):
    store = JsonStore(tmp_path / "source")
    if os.name == "nt":
        # Native failure cleanup is by the created handle, not a path reopen.
        from threaddesk.storage.windows_backup_source import WindowsSourceTree
        original = WindowsSourceTree._check_root

        def fail_late(self):
            original(self)
            if any(self_path.name.startswith(".management-commit-")
                   for self_path in store.root.iterdir()):
                raise ValueError("synthetic failure after exclusive creation")

        monkeypatch.setattr(WindowsSourceTree, "_check_root", fail_late)
    else:
        original = os.replace

        def fail_publish(source, target, **kwargs):
            if target == ".management-commit.json":
                raise OSError("synthetic journal publish failure")
            return original(source, target, **kwargs)

        monkeypatch.setattr(os, "replace", fail_publish)
    with pytest.raises(InvalidState):
        with store.transaction():
            store._write_json(store.root / "normal.json", {"saved": False})
    assert not list(store.root.glob(".management-commit-*.tmp"))
    assert not store._journal.exists()
    assert not (store.root / "normal.json").exists()


@pytest.mark.parametrize("control", [".management.lock", ".management-commit.json"])
def test_control_swapped_to_link_at_first_open_never_opens_external(tmp_path, monkeypatch, control):
    store = JsonStore(tmp_path / "source")
    outside = tmp_path / "external"
    content = b"" if control.endswith("lock") else b'{"version":1,"writes":{}}'
    outside.write_bytes(content)
    selected = store.root / control
    if control.endswith("json"):
        selected.write_bytes(content)
    changed = False
    if os.name == "nt":
        from threaddesk.storage.windows_backup_source import _WindowsAPI
        original = _WindowsAPI._child

        def swap(self, parent, name, **kwargs):
            nonlocal changed
            if name == control and not changed:
                changed = True
                selected.unlink()
                selected.symlink_to(outside)
            return original(self, parent, name, **kwargs)

        monkeypatch.setattr(_WindowsAPI, "_child", swap)
    else:
        original = os.open
        outside_inode = outside.stat().st_ino
        opened_external = []

        def swap(name, flags, *args, **kwargs):
            nonlocal changed
            if name == control and kwargs.get("dir_fd") is not None and not changed:
                changed = True
                selected.unlink()
                selected.symlink_to(outside)
            fd = original(name, flags, *args, **kwargs)
            if os.fstat(fd).st_ino == outside_inode:
                opened_external.append(fd)
            return fd

        monkeypatch.setattr(os, "open", swap)
    with pytest.raises(InvalidState):
        with store.transaction():
            pass
    assert changed
    if os.name != "nt":
        assert not opened_external
    assert outside.read_bytes() == content


def test_ancestor_exchange_before_journal_open_never_reads_external(tmp_path, monkeypatch):
    store = JsonStore(tmp_path / "source")
    journal = store._journal
    journal.write_text('{"version":1,"writes":{}}')
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / journal.name
    secret.write_text('{"version":1,"writes":{"foreign.json":{"bad":true}}}')
    if os.name == "nt":
        # Retained no-delete-sharing root handles must reject the attempted
        # replacement before the native child open can proceed.
        from threaddesk.storage.windows_backup_source import _WindowsAPI
        original = _WindowsAPI._child

        def swap(self, parent, name, **kwargs):
            if name == journal.name:
                store.root.rename(tmp_path / "old-root")
                store.root.symlink_to(outside, target_is_directory=True)
            return original(self, parent, name, **kwargs)

        monkeypatch.setattr(_WindowsAPI, "_child", swap)
    else:
        original = os.open

        def swap(name, flags, *args, **kwargs):
            if name == journal.name and kwargs.get("dir_fd") is not None:
                store.root.rename(tmp_path / "old-root")
                store.root.symlink_to(outside, target_is_directory=True)
            return original(name, flags, *args, **kwargs)

        monkeypatch.setattr(os, "open", swap)
    with pytest.raises(InvalidState):
        with store.transaction():
            pass
    assert not (outside / "foreign.json").exists()
    assert secret.is_file()
