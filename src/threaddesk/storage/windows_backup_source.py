"""Handle-relative Windows backup sources; never reopen a source by pathname.

The root is acquired component by component from a local drive root. Every
component is opened without reparse processing, checked through that same
handle and directories are retained without write/delete sharing. Child acquisition and
directory enumeration are handle-relative, including after root acquisition.
No privileges are enabled. Network roots and every reparse point are refused.
This is not a sandbox against privileged drivers, nor a promise that opening
cloud-provider placeholders cannot trigger provider callbacks or hydration.

Win32 contracts used here (real Windows CI is still required):
https://learn.microsoft.com/windows/win32/api/winternl/nf-winternl-ntcreatefile
https://learn.microsoft.com/windows/win32/api/ntdef/ns-ntdef-_object_attributes
https://learn.microsoft.com/windows/win32/api/fileapi/nf-fileapi-createfilew
https://learn.microsoft.com/windows/win32/api/winbase/nf-winbase-getfileinformationbyhandleex
https://learn.microsoft.com/windows/win32/api/winbase/ns-winbase-file_full_dir_info
"""

from __future__ import annotations

from contextlib import contextmanager
import ctypes
import ntpath
import os
from pathlib import PurePosixPath
import stat
import struct
from uuid import uuid4


def _parts(relative):
    if not isinstance(relative, str) or not relative or "\\" in relative or "\0" in relative:
        raise ValueError("Ungültiger Backup-Pfad.")
    path = PurePosixPath(relative)
    if path.is_absolute() or str(path) != relative or any(
        p in {".", ".."} or ":" in p for p in path.parts
    ):
        raise ValueError("Ungültiger Backup-Pfad.")
    return path.parts


class _WindowsAPI:
    """Small ctypes boundary. Constants are from the Windows SDK, not CRT fds."""

    def __init__(self):
        if os.name != "nt":
            raise OSError("Windows-Handlezugriff ist auf diesem System nicht verfügbar.")
        from ctypes import wintypes as w

        self.w = w
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.native = ctypes.WinDLL("ntdll")

        class UnicodeString(ctypes.Structure):
            _fields_ = [("Length", w.USHORT), ("MaximumLength", w.USHORT),
                        ("Buffer", w.LPWSTR)]

        class ObjectAttributes(ctypes.Structure):
            _fields_ = [("Length", w.ULONG), ("RootDirectory", w.HANDLE),
                        ("ObjectName", ctypes.POINTER(UnicodeString)),
                        ("Attributes", w.ULONG), ("SecurityDescriptor", w.LPVOID),
                        ("SecurityQualityOfService", w.LPVOID)]

        class IOStatus(ctypes.Structure):
            _fields_ = [("Status", ctypes.c_void_p), ("Information", ctypes.c_size_t)]

        self.UnicodeString, self.ObjectAttributes, self.IOStatus = UnicodeString, ObjectAttributes, IOStatus
        self.kernel.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, w.LPVOID,
                                           w.DWORD, w.DWORD, w.HANDLE]
        self.kernel.CreateFileW.restype = w.HANDLE
        self.kernel.CloseHandle.argtypes = [w.HANDLE]
        self.kernel.CloseHandle.restype = w.BOOL
        self.kernel.GetFileInformationByHandleEx.argtypes = [w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD]
        self.kernel.GetFileInformationByHandleEx.restype = w.BOOL
        self.kernel.ReadFile.argtypes = [w.HANDLE, w.LPVOID, w.DWORD, ctypes.POINTER(w.DWORD), w.LPVOID]
        self.kernel.ReadFile.restype = w.BOOL
        self.native.NtCreateFile.argtypes = [ctypes.POINTER(w.HANDLE), w.DWORD,
            ctypes.POINTER(ObjectAttributes), ctypes.POINTER(IOStatus), w.LPVOID,
            w.ULONG, w.ULONG, w.ULONG, w.ULONG, w.LPVOID, w.ULONG]
        self.native.NtCreateFile.restype = ctypes.c_int32
        self.native.RtlNtStatusToDosError.argtypes = [ctypes.c_int32]
        self.native.RtlNtStatusToDosError.restype = w.ULONG

    def anchor(self, path):
        # OPEN_EXISTING; READ/LIST + SYNCHRONIZE; no WRITE or DELETE sharing.
        handle = self.kernel.CreateFileW(path, 0x80100000, 1, None, 3,
                                         0x02200000, None)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        return handle

    def child(self, parent, name):
        # Probe attributes only, then pin the same object with the proper share
        # mode. A directory is NEVER used as a parent while write-shared.
        probe = self._child(parent, name, access=0x00100080, share=3)
        handle = None
        try:
            before = self.stamp(probe)
            handle = self._child(parent, name, access=0x80100000,
                                 share=1 if stat.S_ISDIR(before[2]) else 3)
            after = self.stamp(handle)
            if before[:3] != after[:3]:
                raise ValueError("Backup-Quelle wurde beim Öffnen ausgetauscht.")
            result, handle = handle, None
            return result
        finally:
            if handle is not None:
                self.close(handle)
            self.close(probe)

    def _child(self, parent, name, *, access, share, disposition=1, directory=False):
        if not name or any(c in name for c in "\\/:\0") or name in {".", ".."}:
            raise ValueError("Ungültiger Backup-Pfadbestandteil.")
        buffer = ctypes.create_unicode_buffer(name)
        length = len(name.encode("utf-16-le"))
        if length > 65532:
            raise ValueError("Backup-Pfadbestandteil ist zu lang.")
        text = self.UnicodeString(length, length + 2, ctypes.cast(buffer, self.w.LPWSTR))
        # OBJ_DONT_REPARSE is independently required: share restrictions do not
        # prohibit all attribute-only mutations. If name parsing encounters a
        # newly converted reparse point, fail instead of following it.
        attributes = self.ObjectAttributes(ctypes.sizeof(self.ObjectAttributes), parent,
                                           ctypes.pointer(text), 0x1040, None, None)
        result, status = self.w.HANDLE(), self.IOStatus()
        # A SINGLE child relative to retained directory: no intermediate pathname.
        # FILE_OPEN; SYNCHRONOUS_IO_NONALERT | OPEN_REPARSE_POINT.
        code = self.native.NtCreateFile(ctypes.byref(result), access,
            ctypes.byref(attributes), ctypes.byref(status), None, 0, share, disposition,
            0x00200020 | int(directory), None, 0)
        if code < 0:
            raise ctypes.WinError(self.native.RtlNtStatusToDosError(code))
        return result.value

    def close(self, handle):
        if not self.kernel.CloseHandle(handle):
            raise ctypes.WinError(ctypes.get_last_error())

    def _info(self, handle, kind, size):
        buffer = ctypes.create_string_buffer(size)
        if not self.kernel.GetFileInformationByHandleEx(handle, kind, buffer, size):
            raise ctypes.WinError(ctypes.get_last_error())
        return buffer.raw

    def stamp(self, handle):
        basic = self._info(handle, 0, 40)  # FILE_BASIC_INFO
        standard = self._info(handle, 1, 24)  # FILE_STANDARD_INFO
        identity = self._info(handle, 18, 24)  # FILE_ID_INFO: 128-bit ID (also ReFS)
        created, _, written, changed, attributes = struct.unpack_from("<qqqqI", basic)
        size = struct.unpack_from("<q", standard, 8)[0]
        if attributes & 0x400:  # FILE_ATTRIBUTE_REPARSE_POINT
            raise ValueError("Reparsepoints sind in Backup-Quellen nicht erlaubt.")
        mode = stat.S_IFDIR if standard[21] else stat.S_IFREG
        return (identity[:8], identity[8:], mode, size, written, changed, created)

    def names(self, handle):
        first = True
        while True:
            buffer = ctypes.create_string_buffer(65536)
            if not self.kernel.GetFileInformationByHandleEx(handle, 15 if first else 14,
                                                          buffer, len(buffer)):
                code = ctypes.get_last_error()
                if code == 18:  # ERROR_NO_MORE_FILES
                    return
                raise ctypes.WinError(code)
            first = False
            offset = 0
            while True:
                following, = struct.unpack_from("<I", buffer.raw, offset)
                length, = struct.unpack_from("<I", buffer.raw, offset + 60)
                end = offset + 68 + length
                if length % 2 or end > len(buffer) or (following and following < 68 + length):
                    raise ValueError("Ungültige Windows-Verzeichnisantwort.")
                name = buffer.raw[offset + 68:end].decode("utf-16-le")
                if name not in {".", ".."}:
                    yield name
                if not following:
                    break
                offset += following
                if offset + 68 > len(buffer):
                    raise ValueError("Ungültige Windows-Verzeichnisantwort.")

    def read(self, handle, size):
        buffer = ctypes.create_string_buffer(size)
        count = self.w.DWORD()
        if not self.kernel.ReadFile(handle, buffer, size, ctypes.byref(count), None):
            raise ctypes.WinError(ctypes.get_last_error())
        return buffer.raw[:count.value]


class _Reader:
    def __init__(self, api, handle, validate):
        self.api, self.handle, self.validate = api, handle, validate

    def read(self, size=-1):
        chunks = []
        while size != 0:
            self.validate()
            chunk = self.api.read(self.handle, min(size, 1024 * 1024) if size >= 0 else 1024 * 1024)
            self.validate()
            if not chunk:
                break
            chunks.append(chunk)
            if size > 0:
                size -= len(chunk)
        return b"".join(chunks)


class WindowsSourceTree:
    def __init__(self, root, *, error_type=RuntimeError, _api=None, _allow_unc_controls=False):
        self.error_type, self.handles, self.directories = error_type, [], {}
        self.root_guards = []
        try:
            self.api = _api if _api is not None else _WindowsAPI()
            path = ntpath.abspath(os.fspath(root))
            drive, tail = ntpath.splitdrive(path)
            local = len(drive) == 2 and drive[1] == ":" and tail.startswith("\\")
            unc = (_allow_unc_controls and drive.startswith("\\\\")
                   and len(drive.lstrip("\\").split("\\")) == 2
                   and (not tail or tail.startswith("\\")))
            if not local and not unc:
                raise ValueError("Sichere Backup-Quellen erfordern ein lokales Windows-Laufwerk.")
            parent = self.api.anchor(drive + "\\")
            self.handles.append(parent)
            self.root_guards.append((parent, self._directory(parent)[:2]))
            for name in tail.split("\\"):
                if not name:
                    continue
                parent = self.api.child(parent, name)
                self.handles.append(parent)
                self.root_guards.append((parent, self._directory(parent)[:2]))
            self.root = parent
        except (OSError, ValueError) as exc:
            self.__exit__()
            raise self.error_type(str(exc)) from exc

    def __enter__(self):
        try:
            self._check_root()
        except (OSError, ValueError) as exc:
            self.__exit__()
            raise self.error_type(str(exc)) from exc
        return self

    def __exit__(self, *args):
        while self.handles:
            self.api.close(self.handles.pop())

    def _directory(self, handle):
        value = self.api.stamp(handle)
        if not stat.S_ISDIR(value[2]):
            raise ValueError("Backup-Quellverzeichnis ist kein reguläres Verzeichnis.")
        return value

    def _check_root(self):
        for handle, identity in self.root_guards:
            if self._directory(handle)[:2] != identity:
                raise ValueError("Backup-Quellverzeichnis wurde ausgetauscht.")

    @contextmanager
    def control_lock(self):
        """Only JsonStore's fixed lock; no general pathname-writing API.

        UNC controls use the same native identity/no-reparse requirements;
        unsupported server primitives fail explicitly, never fall back to paths.
        Native local Windows CI does not attest SMB-server behavior.
        """
        import msvcrt
        handle = None
        try:
            self._check_root()
            handle = self.api._child(self.root, ".management.lock", access=0xC0100000,
                                     share=3, disposition=3)  # FILE_OPEN_IF
            before = self.api.stamp(handle)
            if not stat.S_ISREG(before[2]):
                raise ValueError("Ungültige JSON-Sperrdatei.")
            standard = self.api._info(handle, 1, 24)
            if struct.unpack_from("<I", standard, 16)[0] != 1:
                raise ValueError("Verknüpfte JSON-Sperrdatei ist nicht erlaubt.")
            fd = msvcrt.open_osfhandle(handle, os.O_RDWR | os.O_BINARY)
            handle = None  # The CRT now owns the native handle.
            try:
                stream = os.fdopen(fd, "r+b")
            except BaseException:
                os.close(fd)
                raise
            with stream:
                native = msvcrt.get_osfhandle(stream.fileno())

                def validate():
                    self._check_root()
                    if self.api.stamp(native)[:2] != before[:2]:
                        raise ValueError("JSON-Sperrdatei wurde ausgetauscht.")

                validate()
                yield stream, validate
                validate()
        except (OSError, ValueError) as exc:
            raise self.error_type(str(exc)) from exc
        finally:
            if handle is not None:
                self.api.close(handle)

    def remove_control_journal(self, expected):
        """Delete exactly the checked journal object, not a reopened path alias."""
        self._check_root()
        handle = self.api._child(self.root, ".management-commit.json",
                                 access=0x00110080, share=3)
        try:
            if self.api.stamp(handle) != expected:
                raise ValueError("JSON-Journal wurde ausgetauscht.")
            self._discard_control_handle(handle)
        finally:
            self.api.close(handle)

    def check_control_journal_links(self, reader):
        standard = self.api._info(reader.handle, 1, 24)
        if struct.unpack_from("<I", standard, 16)[0] != 1:
            raise ValueError("Verknüpftes JSON-Journal ist nicht erlaubt.")

    def _discard_control_handle(self, handle):
        delete = self.api.w.BOOL(True)
        function = self.api.kernel.SetFileInformationByHandle
        function.argtypes = [self.api.w.HANDLE, ctypes.c_int,
                             self.api.w.LPVOID, self.api.w.DWORD]
        function.restype = self.api.w.BOOL
        if not function(handle, 4, ctypes.byref(delete), ctypes.sizeof(delete)):
            raise ctypes.WinError(ctypes.get_last_error())

    def publish_control_journal(self, body):
        """Publish only the fixed JSON WAL from an exclusive native temp handle."""
        self._publish_recovery_bytes(self.root, ".management-commit.json", body,
                                     self._check_root, prefix=".management-commit-")

    @contextmanager
    def _recovery_parent(self, parts, *, create):
        parent, opened, guards = self.root, [], []

        def validate():
            self._check_root()
            for handle, identity in guards:
                if self._directory(handle)[:2] != identity:
                    raise ValueError("JSON-Recovery-Verzeichnis wurde ausgetauscht.")

        try:
            validate()
            for name in parts:
                validate()
                parent = self.api._child(parent, name, access=0x00100081, share=1,
                                         disposition=3 if create else 1, directory=True)
                opened.append(parent)
                guards.append((parent, self._directory(parent)[:2]))
            validate()
            yield parent, validate
            validate()
        finally:
            for handle in reversed(opened):
                self.api.close(handle)

    def recover_data_entry(self, parts, body):
        """Only validated JSON-WAL entries use these retained parent handles."""
        try:
            with self._recovery_parent(parts[:-1], create=body is not None) as (parent, validate):
                if body is None:
                    validate()
                    handle = self.api._child(parent, parts[-1], access=0x00110080, share=3)
                    try:
                        if not stat.S_ISREG(self.api.stamp(handle)[2]):
                            raise ValueError("Ungültige JSON-Recovery-Datei.")
                        validate()
                        self._discard_control_handle(handle)
                    finally:
                        self.api.close(handle)
                else:
                    self._publish_recovery_bytes(parent, parts[-1], body, validate)
        except FileNotFoundError:
            self._check_root()
            if body is not None:
                raise

    def _publish_recovery_bytes(self, parent, leaf, body, validate, *, prefix=".management-data-"):
        """Handle publisher restricted to the fixed WAL and its replay callers."""
        import msvcrt

        handle, published = None, False
        try:
            validate()
            name = prefix + uuid4().hex + ".tmp"
            handle = self.api._child(parent, name, access=0xC0110000,
                                     share=0, disposition=2)  # FILE_CREATE, exclusive
            if not stat.S_ISREG(self.api.stamp(handle)[2]):
                raise ValueError("Ungültiges JSON-Journalziel.")
            fd = msvcrt.open_osfhandle(handle, os.O_RDWR | os.O_BINARY)
            handle = None
            try:
                stream = os.fdopen(fd, "w+b")
            except BaseException:
                try:
                    self._discard_control_handle(msvcrt.get_osfhandle(fd))
                finally:
                    os.close(fd)
                raise
            with stream:
                native = msvcrt.get_osfhandle(stream.fileno())
                try:
                    validate()
                    stream.write(body)
                    stream.flush()
                    os.fsync(stream.fileno())

                    class Rename(ctypes.Structure):
                        _fields_ = [("ReplaceIfExists", self.api.w.BOOL),
                                    ("RootDirectory", self.api.w.HANDLE),
                                    ("FileNameLength", self.api.w.DWORD),
                                    ("FileName", self.api.w.WCHAR * 1)]

                    # FileRenameInfo resolves this fixed leaf against the held
                    # directory; no full source/destination pathname is reopened.
                    encoded = leaf.encode("utf-16-le")
                    buffer = ctypes.create_string_buffer(ctypes.sizeof(Rename) + len(encoded))
                    rename = Rename.from_buffer(buffer)
                    rename.ReplaceIfExists, rename.RootDirectory = True, parent
                    rename.FileNameLength = len(encoded)
                    ctypes.memmove(ctypes.addressof(buffer) + Rename.FileName.offset, encoded, len(encoded))
                    function = self.api.kernel.SetFileInformationByHandle
                    function.argtypes = [self.api.w.HANDLE, ctypes.c_int,
                                         self.api.w.LPVOID, self.api.w.DWORD]
                    function.restype = self.api.w.BOOL
                    validate()
                    if not function(native, 3, buffer, len(buffer)):
                        raise ctypes.WinError(ctypes.get_last_error())
                    published = True
                finally:
                    if not published:
                        self._discard_control_handle(native)
        except (OSError, ValueError) as exc:
            raise self.error_type(str(exc)) from exc
        finally:
            if handle is not None:
                try:
                    self._discard_control_handle(handle)
                finally:
                    self.api.close(handle)

    @contextmanager
    def _parent(self, parts):
        parent, opened, guards = self.root, [], []

        def validate():
            self._check_root()
            for handle, identity in guards:
                if self._directory(handle)[:2] != identity:
                    raise ValueError("Backup-Quellverzeichnis wurde ausgetauscht.")

        try:
            validate()
            for index, name in enumerate(parts):
                validate()
                parent = self.api.child(parent, name)
                opened.append(parent)
                info = self._directory(parent)
                key = "/".join(parts[:index + 1])
                if self.directories.get(key, info[:2]) != info[:2]:
                    raise ValueError("Backup-Quellverzeichnis wurde ausgetauscht.")
                guards.append((parent, info[:2]))
            validate()
            yield parent, validate
            validate()
        except (OSError, ValueError) as exc:
            raise self.error_type(str(exc)) from exc
        finally:
            for handle in reversed(opened):
                self.api.close(handle)

    @contextmanager
    def _file(self, relative):
        handle = None
        try:
            parts = _parts(relative)
            with self._parent(parts[:-1]) as (directory, validate):
                handle = self.api.child(directory, parts[-1])
                validate()
                yield handle, validate
                validate()
        except (OSError, ValueError) as exc:
            raise self.error_type(str(exc)) from exc
        finally:
            if handle is not None:
                self.api.close(handle)

    def info(self, relative):
        with self._file(relative) as (handle, _):
            return self.api.stamp(handle)

    def scan(self, allowed, descend):
        files = {}

        def walk(parts):
            with self._parent(parts) as (directory, validate):
                for name in sorted(self.api.names(directory)):
                    validate()
                    relative = "/".join((*parts, name))
                    if not allowed(relative) and not descend(relative):
                        continue
                    with self._file(relative) as (handle, _):
                        value = self.api.stamp(handle)
                    if stat.S_ISDIR(value[2]):
                        if descend(relative):
                            if self.directories.setdefault(relative, value[:2]) != value[:2]:
                                raise ValueError("Backup-Quellverzeichnis wurde ausgetauscht.")
                            walk((*parts, name))
                    elif allowed(relative):
                        if not stat.S_ISREG(value[2]):
                            raise ValueError("Backup-Quelle enthält keine reguläre Datei.")
                        files[relative] = value
        walk(())
        return files

    @contextmanager
    def open(self, relative, expected):
        with self._file(relative) as (handle, ancestors):
            def validate():
                ancestors()
                if self.api.stamp(handle) != expected or not stat.S_ISREG(expected[2]):
                    raise ValueError("Backup-Quelldatei wurde ausgetauscht oder verändert.")

            validate()
            yield _Reader(self.api, handle, validate)
            validate()

    def read(self, relative, expected, *, limit=None):
        with self.open(relative, expected) as handle:
            if limit is not None and expected[3] > limit:
                raise self.error_type("Workspace exceeds the backup size limit.")
            body = handle.read() if limit is None else handle.read(limit + 1)
            if limit is not None and len(body) > limit:
                raise self.error_type("Workspace exceeds the backup size limit.")
            return body
