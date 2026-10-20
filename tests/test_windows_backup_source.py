"""Portable contract checks plus native Windows assertions (no skipped tests)."""

import io
import os
import stat

import pytest

from threaddesk.storage.windows_backup_source import WindowsSourceTree


class SourceError(RuntimeError):
    pass


class FakeAPI:
    """Handle model tests routing/order only; it cannot attest Win32 semantics."""

    def __init__(self):
        self.nodes = {"volume": {"work": "root"}, "root": {"folder": "dir", "a": "file"},
                      "dir": {"b": "nested"}, "file": b"abc", "nested": b"hello"}
        self.reparse, self.closed, self.reads = set(), [], []
        self.positions = {}
        self.serial = 0
        self.handles = {}
        self.children = []

    def _handle(self, node):
        self.serial += 1
        self.handles[self.serial] = node
        return self.serial

    def anchor(self, path):
        assert path == "C:\\"
        return self._handle("volume")

    def child(self, parent, name):
        assert parent not in self.closed
        self.children.append((parent, name))
        return self._handle(self.nodes[self.handles[parent]][name])

    def close(self, handle):
        assert handle not in self.closed
        self.closed.append(handle)

    def stamp(self, handle):
        node = self.handles[handle]
        if node in self.reparse:
            raise ValueError("Reparsepoint")
        value = self.nodes[node]
        return (1, node, stat.S_IFDIR if isinstance(value, dict) else stat.S_IFREG,
                0 if isinstance(value, dict) else len(value), 1, 1)

    def names(self, handle):
        return tuple(self.nodes[self.handles[handle]])

    def read(self, handle, size):
        self.reads.append(handle)
        value = self.nodes[self.handles[handle]]
        start = self.positions.get(handle, 0)
        self.positions[handle] = start + size
        return value[start:start + size]


def tree(api):
    return WindowsSourceTree("C:\\work", error_type=SourceError, _api=api)


def test_handle_relative_inventory_and_stream_copy():
    api = FakeAPI()
    with tree(api) as source:
        inventory = source.scan(lambda _: True, lambda _: True)
        assert set(inventory) == {"a", "folder/b"}
        output = io.BytesIO()
        with source.open("folder/b", inventory["folder/b"]) as handle:
            output.write(handle.read(2))
            output.write(handle.read())
        assert output.getvalue() == b"hello"
        assert source.read("a", inventory["a"], limit=3) == b"abc"
    assert len(api.closed) == len(api.handles)


def test_reparse_root_rejected_before_first_read_and_all_handles_closed():
    api = FakeAPI()
    api.reparse.add("root")
    with pytest.raises(SourceError, match="Reparse"):
        tree(api)
    assert not api.reads
    assert len(api.closed) == len(api.handles)


@pytest.mark.parametrize("ancestor", ["root", "volume"])
def test_root_or_ancestor_reparsed_after_construction_blocks_child_and_read(ancestor):
    api = FakeAPI()
    with tree(api) as source:
        expected = source.info("a")
        children = list(api.children)
        api.reparse.add(ancestor)
        with pytest.raises(SourceError, match="Reparse"):
            source.read("a", expected)
        assert api.children == children
        assert not api.reads


def test_ancestor_reparsed_after_open_blocks_first_chunk():
    api = FakeAPI()
    with tree(api) as source:
        expected = source.info("a")
        with pytest.raises(SourceError, match="Reparse"):
            with source.open("a", expected) as handle:
                api.reparse.add("root")
                handle.read()
        assert not api.reads


@pytest.mark.parametrize("relative", ["a", "folder/b"])
def test_replaced_or_reparsed_leaf_rejected_before_first_read(relative):
    api = FakeAPI()
    with tree(api) as source:
        expected = source.info(relative)
        node = "file" if relative == "a" else "nested"
        api.reparse.add(node)
        with pytest.raises(SourceError, match="Reparse"):
            source.read(relative, expected)
        assert not api.reads


def test_replaced_parent_is_rejected_before_read():
    api = FakeAPI()
    with tree(api) as source:
        inventory = source.scan(lambda _: True, lambda _: True)
        api.nodes["other"] = {"b": "nested"}
        api.nodes["root"]["folder"] = "other"
        with pytest.raises(SourceError, match="ausgetauscht"):
            source.read("folder/b", inventory["folder/b"])
        assert not api.reads


def test_size_limit_checks_before_first_read():
    api = FakeAPI()
    with tree(api) as source:
        with pytest.raises(SourceError, match="size limit"):
            source.read("a", source.info("a"), limit=2)
        assert not api.reads


def test_changed_leaf_stamp_rejected_before_first_read():
    api = FakeAPI()
    with tree(api) as source:
        expected = source.info("a")
        api.nodes["file"] = b"modified"
        with pytest.raises(SourceError, match="verändert"):
            source.read("a", expected)
        assert not api.reads


def test_inflight_mutation_rejects_the_capture():
    api = FakeAPI()
    with tree(api) as source:
        expected = source.info("a")
        with pytest.raises(SourceError, match="verändert"):
            with source.open("a", expected) as handle:
                assert handle.read(1) == b"a"
                api.nodes["file"] = b"changed"


def test_bound_root_handle_does_not_reopen_a_changed_root_name():
    api = FakeAPI()
    with tree(api) as source:
        expected = source.info("a")
        # A real no-delete-sharing handle blocks this rename; the stronger
        # synthetic replacement also verifies that reads use the retained root.
        api.nodes["volume"]["work"] = "other"
        api.nodes["other"] = {"a": "secret"}
        api.nodes["secret"] = b"outside"
        assert source.read("a", expected) == b"abc"


def test_unc_controls_have_explicit_internal_routing_without_claiming_native_smb():
    class UNCModel(FakeAPI):
        def anchor(self, path):
            assert path == "\\\\server\\share\\"
            return self._handle("volume")

    with pytest.raises(SourceError, match="lokales"):
        WindowsSourceTree("\\\\server\\share\\work", error_type=SourceError, _api=UNCModel())
    with WindowsSourceTree("\\\\server\\share\\work", error_type=SourceError,
                           _api=UNCModel(), _allow_unc_controls=True) as source:
        assert source.read("a", source.info("a")) == b"abc"


@pytest.mark.parametrize("relative", ["../a", "/a", "folder/../a", "a:stream", "a\\b", "a\0"])
def test_invalid_paths_rejected_before_first_read(relative):
    api = FakeAPI()
    with tree(api) as source:
        with pytest.raises(SourceError):
            source.info(relative)
        assert not api.reads


def test_native_windows_read_and_rename_lock_or_explicit_unsupported(tmp_path):
    if os.name != "nt":
        with pytest.raises(SourceError, match="Windows-Handlezugriff"):
            WindowsSourceTree(tmp_path, error_type=SourceError)
        return
    root = tmp_path / "source"
    root.mkdir()
    file = root / "file"
    file.write_bytes(b"native")
    with WindowsSourceTree(root, error_type=SourceError) as source:
        inventory = source.scan(lambda _: True, lambda _: True)
        with source.open("file", inventory["file"]) as handle:
            with pytest.raises(OSError):
                file.rename(root / "renamed")
            assert handle.read() == b"native"
        with pytest.raises(OSError):
            root.rename(tmp_path / "renamed-root")
        assert source.read("file", inventory["file"], limit=6) == b"native"


def test_native_windows_journal_and_nested_recovery_publish_in_bound_parent_or_unsupported(tmp_path):
    if os.name != "nt":
        with pytest.raises(SourceError, match="Windows-Handlezugriff"):
            WindowsSourceTree(tmp_path, error_type=SourceError)
        return
    root = tmp_path / "source"
    root.mkdir()
    with WindowsSourceTree(root, error_type=SourceError) as source:
        source.publish_control_journal(b"first")
        assert source.read(".management-commit.json", source.info(".management-commit.json")) == b"first"
        source.publish_control_journal(b"second")
        assert source.read(".management-commit.json", source.info(".management-commit.json")) == b"second"
        source.recover_data_entry(("new", "nested", "record.json"), b'{"saved":true}')
        assert source.read("new/nested/record.json", source.info("new/nested/record.json")) == b'{"saved":true}'
        source.recover_data_entry(("new", "nested", "record.json"), None)
        with pytest.raises(SourceError):
            source.info("new/nested/record.json")
        source.remove_control_journal(source.info(".management-commit.json"))
        assert not list(root.rglob("*.tmp"))


def test_native_windows_directory_writer_blocked_or_explicit_unsupported(tmp_path):
    if os.name != "nt":
        with pytest.raises(SourceError, match="Windows-Handlezugriff"):
            WindowsSourceTree(tmp_path, error_type=SourceError)
        return
    import ctypes
    root = tmp_path / "source"
    root.mkdir()
    with WindowsSourceTree(root, error_type=SourceError) as source:
        handle = source.api.kernel.CreateFileW(str(root), 0x40000000, 7, None,
                                               3, 0x02200000, None)
        if handle != ctypes.c_void_p(-1).value:
            source.api.close(handle)
            pytest.fail("Gehaltener Quellordner erlaubt einen Schreibhandle.")
        assert ctypes.get_last_error() == 32  # ERROR_SHARING_VIOLATION


def test_native_windows_existing_directory_writer_aborts_or_explicit_unsupported(tmp_path):
    if os.name != "nt":
        with pytest.raises(SourceError, match="Windows-Handlezugriff"):
            WindowsSourceTree(tmp_path, error_type=SourceError)
        return
    import ctypes
    from threaddesk.storage.windows_backup_source import _WindowsAPI
    root = tmp_path / "source"
    root.mkdir()
    api = _WindowsAPI()
    handle = api.kernel.CreateFileW(str(root), 0x40000000, 7, None,
                                   3, 0x02200000, None)
    assert handle != ctypes.c_void_p(-1).value
    try:
        with pytest.raises(SourceError):
            WindowsSourceTree(root, error_type=SourceError)
    finally:
        api.close(handle)
    with WindowsSourceTree(root, error_type=SourceError) as source:
        assert source.scan(lambda _: True, lambda _: True) == {}


def test_native_windows_reparse_race_never_reads_external_secret_or_explicit_unsupported(tmp_path):
    if os.name != "nt":
        with pytest.raises(SourceError, match="Windows-Handlezugriff"):
            WindowsSourceTree(tmp_path, error_type=SourceError)
        return
    import ctypes
    from ctypes import wintypes as w
    import struct
    root, outside = tmp_path / "source", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "secret").write_bytes(b"must never be read")
    with WindowsSourceTree(outside, error_type=SourceError) as external:
        expected = external.info("secret")
    converted = False
    attempted = False
    reads = []
    try:
        with WindowsSourceTree(root, error_type=SourceError) as source:
            original_child, original_read = source.api.child, source.api.read

            def read(handle, size):
                reads.append(handle)
                return original_read(handle, size)

            def convert_then_open(parent, name):
                nonlocal converted, attempted
                assert not attempted
                attempted = True
                # This callback runs AFTER _parent validated the held root and
                # BEFORE child acquisition, not merely before source.read().
                handle = source.api.kernel.CreateFileW(str(root), 0x100, 7, None,
                                                       3, 0x02200000, None)
                if handle == ctypes.c_void_p(-1).value:
                    assert ctypes.get_last_error() in {5, 32}
                    return original_child(parent, name)
                try:
                    substitute = ("\\??\\" + str(outside)).encode("utf-16-le")
                    printed = str(outside).encode("utf-16-le")
                    paths = substitute + b"\0\0" + printed + b"\0\0"
                    data = struct.pack("<HHHH", 0, len(substitute), len(substitute) + 2,
                                       len(printed)) + paths
                    request = struct.pack("<IHH", 0xA0000003, len(data), 0) + data
                    buffer = ctypes.create_string_buffer(request)
                    count = w.DWORD()
                    ioctl = source.api.kernel.DeviceIoControl
                    ioctl.argtypes = [w.HANDLE, w.DWORD, w.LPVOID, w.DWORD,
                                      w.LPVOID, w.DWORD, ctypes.POINTER(w.DWORD), w.LPVOID]
                    ioctl.restype = w.BOOL
                    converted = bool(ioctl(handle, 0x900A4, buffer, len(request),
                                           None, 0, ctypes.byref(count), None))
                    if not converted:
                        assert ctypes.get_last_error() in {5, 32}
                finally:
                    source.api.close(handle)
                return original_child(parent, name)

            source.api.child, source.api.read = convert_then_open, read
            with pytest.raises(SourceError):
                source.read("secret", expected)
            assert attempted
            assert reads == []
    finally:
        if converted:
            # Remove only the temporary junction, never its external target.
            os.rmdir(root)
    assert (outside / "secret").read_bytes() == b"must never be read"


def test_native_windows_junction_rejected_or_explicit_unsupported(tmp_path):
    if os.name != "nt":
        with pytest.raises(SourceError, match="Windows-Handlezugriff"):
            WindowsSourceTree(tmp_path, error_type=SourceError)
        return
    # Junction creation needs neither developer mode nor symlink privilege.
    import subprocess
    root, outside = tmp_path / "root", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "secret").write_bytes(b"not a source")
    junction = root / "junction"
    subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
                   check=True, capture_output=True)
    try:
        with WindowsSourceTree(root, error_type=SourceError) as source:
            with pytest.raises(SourceError, match="Reparse"):
                source.scan(lambda _: True, lambda _: True)
    finally:
        os.rmdir(junction)
