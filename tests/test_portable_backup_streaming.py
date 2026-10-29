"""Large native backups and hostile archives preserve data without live activation."""
import hashlib
import io
import json
import os
import stat
import warnings
import zipfile
from contextlib import contextmanager
from pathlib import Path

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.storage import portable_backup as portable
from threaddesk.storage import workspace_backup
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore
from threaddesk.storage.workspace_backup import BackupError


def digest_file(path):
    result = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            result.update(block)
    return result.hexdigest()


def new_source(tmp_path, backend=JsonStore):
    store = backend(tmp_path / "source")
    svc = ThreadService(store)
    thread = svc.create("Original project")
    svc.set_note("Original notes remain", thread.id)
    svc.append_whiteboard(thread.id, actor="Human", actor_type="human",
                          entry_type="note", content="Original whiteboard entry")
    return store, thread


def write_archive(path, manifest, payloads, *, modes=None, duplicate=None):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest).encode())
            for name, body in payloads.items():
                info = zipfile.ZipInfo(name)
                info.compress_type = zipfile.ZIP_DEFLATED
                if modes and name in modes:
                    info.create_system = 3
                    info.external_attr = modes[name] << 16
                archive.writestr(info, body)
            if duplicate:
                archive.writestr(duplicate, b"duplicate")
    return path


def archive_parts(path):
    with zipfile.ZipFile(path) as archive:
        return (json.loads(archive.read("manifest.json")),
                {n: archive.read(n) for n in archive.namelist() if n != "manifest.json"})


def assert_failed_restore_preserved_selection(path, root, old_marker):
    with pytest.raises(BackupError):
        portable.restore_backup(path, root)
    assert (root / "active-profile.json").read_bytes() == old_marker
    assert {p.name for p in (root / "profiles").iterdir()} == {"a" * 32}
    assert (root / "profiles" / ("a" * 32) / "retain.txt").read_bytes() == b"keep"


def existing_profile(tmp_path):
    root = tmp_path / "restore"
    old = root / "profiles" / ("a" * 32)
    old.mkdir(parents=True)
    (old / "retain.txt").write_bytes(b"keep")
    marker = json.dumps({"name": "a" * 32, "backend": "json"}).encode()
    (root / "active-profile.json").write_bytes(marker)
    return root, marker


@pytest.mark.parametrize("backend", [JsonStore, SQLiteStore], ids=["json", "sqlite"])
def test_streaming_export_preserves_business_documents_and_core(tmp_path, backend):
    store, thread = new_source(tmp_path, backend)
    originals = {}
    for folder in ("Tool-Planung", "Workflow", "Zukunftsvisionen", "Bilder"):
        path = store.root / folder / "nested" / "original.bin"
        path.parent.mkdir(parents=True)
        path.write_bytes(folder.encode() + b"\x00\xff\n")
        originals[path.relative_to(store.root).as_posix()] = path.read_bytes()
    target = tmp_path / "backup.zip"
    try:
        summary = portable.export_backup(store, target)
        assert summary["verified"] is True
        assert summary["sha256"] == digest_file(target)
        assert portable.inspect_backup(target)["verified"] is True
        restored = backend(portable.restore_backup(target, tmp_path / "restore"))
        try:
            assert restored.get_thread(thread.id).context.notes == "Original notes remain"
            assert restored.list_whiteboard(thread.id)[0].content == "Original whiteboard entry"
            for name, body in originals.items():
                assert (restored.root / name).read_bytes() == body
                assert (store.root / name).read_bytes() == body
        finally:
            if backend is SQLiteStore:
                restored.connection.close()
    finally:
        if backend is SQLiteStore:
            store.connection.close()


def test_large_payload_uses_bounded_source_reads_and_survives_native_restore(tmp_path, monkeypatch):
    store, thread = new_source(tmp_path)
    original = store.root / "artifacts" / "large.bin"
    original.parent.mkdir()
    with original.open("wb") as output:
        output.write(b"BEGIN\x00\xff")
        output.seek(129 * 1024 * 1024)
        output.write(b"END\n")
    expected = digest_file(original)
    reader = workspace_backup._SourceTree
    original_open = reader.open
    reads = []

    class BoundedPayload:
        def __init__(self, handle):
            self.handle = handle

        def __getattr__(self, name):
            return getattr(self.handle, name)

        def read(self, size=-1):
            assert 0 < size <= 1024 * 1024, "source payload must be read in bounded chunks"
            reads.append(size)
            return self.handle.read(size)

    @contextmanager
    def bounded_open(self, relative, expected_stat):
        with original_open(self, relative, expected_stat) as handle:
            if self.path.resolve() == store.root.resolve() and relative == "artifacts/large.bin":
                yield BoundedPayload(handle)
            else:
                yield handle

    monkeypatch.setattr(reader, "open", bounded_open)
    archive = tmp_path / "large.zip"
    portable.export_backup(store, archive)
    assert reads
    assert portable.inspect_backup(archive)["verified"] is True
    restored = portable.restore_backup(archive, tmp_path / "restore")
    assert (restored / "artifacts/large.bin").stat().st_size == original.stat().st_size
    assert digest_file(restored / "artifacts/large.bin") == expected == digest_file(original)
    assert JsonStore(restored).get_thread(thread.id).title == thread.title


def test_more_than_twenty_thousand_payload_files_roundtrip_without_omission(tmp_path):
    store, _ = new_source(tmp_path)
    artifacts = store.root / "artifacts"
    artifacts.mkdir()
    for i in range(20010):
        (artifacts / f"item-{i:05}.bin").write_bytes(i.to_bytes(4, "little"))
    archive = tmp_path / "many.zip"
    portable.export_backup(store, archive)
    restored = portable.restore_backup(archive, tmp_path / "restore")
    assert len(list((restored / "artifacts").iterdir())) == 20010
    for i in range(20010):
        assert (restored / "artifacts" / f"item-{i:05}.bin").read_bytes() == i.to_bytes(4, "little")


class BoundedArchive(io.BytesIO):
    """Allow ZIP's small end records, but refuse an unbounded whole-file read."""
    def read(self, size=-1):
        remaining = self.getbuffer().nbytes - self.tell()
        assert size >= 0 or remaining <= 1024 * 1024
        assert size <= 1024 * 1024
        return super().read(size)


def test_inspect_and_restore_accept_seekable_sources_without_reading_whole_archive(tmp_path):
    store, thread = new_source(tmp_path)
    payload = store.root / "artifacts" / "random.bin"
    payload.parent.mkdir()
    payload.write_bytes(os.urandom(3 * 1024 * 1024))
    archive = tmp_path / "random.zip"
    portable.export_backup(store, archive)
    body = archive.read_bytes()
    assert len(body) > 2 * 1024 * 1024
    assert portable.inspect_backup(BoundedArchive(body))["verified"] is True
    restored = portable.restore_backup(BoundedArchive(body), tmp_path / "restore")
    assert digest_file(restored / "artifacts/random.bin") == digest_file(payload)
    assert JsonStore(restored).get_thread(thread.id).title == thread.title


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("backend", [JsonStore, SQLiteStore], ids=["json", "sqlite"])
def test_legacy_archives_still_restore_via_bytes_path_and_seekable(tmp_path, version, backend):
    store, thread = new_source(tmp_path, backend)
    archive = tmp_path / "modern.zip"
    try:
        portable.export_backup(store, archive)
        manifest, payloads = archive_parts(archive)
        manifest["version"] = version
        manifest.pop("symlinks", None)
        manifest.pop("directories", None)
        manifest.pop("consistency", None)
        legacy = write_archive(tmp_path / "legacy.zip", manifest, payloads)
        for label, source in (("bytes", legacy.read_bytes()), ("path", legacy),
                              ("seekable", io.BytesIO(legacy.read_bytes()))):
            assert portable.inspect_backup(source)["verified"] is True
            if hasattr(source, "seek"):
                source.seek(0)
            restored = backend(portable.restore_backup(source, tmp_path / label))
            try:
                assert restored.get_thread(thread.id).context.notes == "Original notes remain"
                assert restored.list_whiteboard(thread.id)[0].content == "Original whiteboard entry"
            finally:
                if backend is SQLiteStore:
                    restored.connection.close()
    finally:
        if backend is SQLiteStore:
            store.connection.close()


def test_export_never_overwrites_existing_destination_or_captures_itself(tmp_path):
    store, _ = new_source(tmp_path)
    destination = tmp_path / "existing.zip"
    destination.write_bytes(b"retain original archive")
    with pytest.raises(BackupError):
        portable.export_backup(store, destination)
    assert destination.read_bytes() == b"retain original archive"
    inside = store.root / "artifacts" / "self.zip"
    inside.parent.mkdir()
    with pytest.raises(BackupError):
        portable.export_backup(store, inside)
    assert not inside.exists()


def test_export_failure_keeps_source_and_publishes_no_partial_archive(tmp_path):
    store, thread = new_source(tmp_path)
    outside = tmp_path / "outside"
    outside.write_bytes(b"DO NOT READ OR MODIFY")
    original_thread = store.root / "threads" / (thread.id + ".json")
    original_thread.unlink()
    original_thread.symlink_to(outside)
    archive = tmp_path / "backup.zip"
    with pytest.raises(BackupError):
        portable.export_backup(store, archive)
    assert not archive.exists()
    assert not list(tmp_path.glob("*.partial"))
    assert outside.read_bytes() == b"DO NOT READ OR MODIFY"
    assert original_thread.is_symlink()


@pytest.mark.parametrize("setting,limit", [("max_bytes", 300), ("max_files", 1),
                                           ("max_manifest_bytes", 32)])
def test_explicit_limits_fail_before_publishing_or_changing_active_profile(tmp_path, setting, limit):
    store, _ = new_source(tmp_path)
    archive = tmp_path / "backup.zip"
    portable.export_backup(store, archive)
    root, marker = existing_profile(tmp_path)
    with pytest.raises(BackupError):
        portable.inspect_backup(archive, **{setting: limit})
    with pytest.raises(BackupError):
        portable.restore_backup(archive, root, **{setting: limit})
    assert (root / "active-profile.json").read_bytes() == marker
    assert {p.name for p in (root / "profiles").iterdir()} == {"a" * 32}
    limited = tmp_path / "limited.zip"
    with pytest.raises(BackupError):
        portable.export_backup(store, limited, **{setting: limit})
    assert not limited.exists()


@pytest.mark.parametrize("attack", ["checksum", "duplicate", "unlisted", "crc", "zipbomb", "fifo"])
def test_hostile_archives_never_change_selected_profile(tmp_path, attack):
    store, _ = new_source(tmp_path)
    archive = tmp_path / "valid.zip"
    portable.export_backup(store, archive)
    manifest, payloads = archive_parts(archive)
    selected = next(iter(payloads))
    modes = None
    duplicate = None
    if attack == "checksum":
        payloads[selected] += b"forged"
    elif attack == "duplicate":
        duplicate = selected
    elif attack == "unlisted":
        payloads["workspace/artifacts/not-listed.txt"] = b"unexpected"
    elif attack == "fifo":
        modes = {selected: stat.S_IFIFO | 0o600}
    elif attack == "zipbomb":
        payloads[selected] = b"A" * (2 * 1024 * 1024)
    broken = write_archive(tmp_path / "broken.zip", manifest, payloads, modes=modes, duplicate=duplicate)
    if attack == "crc":
        # Corrupt the stored expected CRC, rather than a DEFLATE padding bit
        # that may leave the decoded payload unchanged.
        with zipfile.ZipFile(broken, "a") as z:
            z.getinfo(selected).CRC ^= 1
            # The public comment setter commits the updated central directory.
            z.comment = b"intentional CRC mismatch"
        with zipfile.ZipFile(broken) as z:
            with pytest.raises(zipfile.BadZipFile):
                z.read(selected)
    root, marker = existing_profile(tmp_path)
    assert_failed_restore_preserved_selection(broken, root, marker)
    with pytest.raises(BackupError):
        portable.inspect_backup(broken)


@pytest.mark.parametrize("target", ["../../outside", "/private/unavailable/secret", "missing-relative"])
def test_artifact_links_remain_inert_across_restore_and_reexport(tmp_path, target):
    store, _ = new_source(tmp_path)
    artifacts = store.root / "artifacts"
    artifacts.mkdir()
    link = artifacts / "reference"
    link.symlink_to(target)
    outside = tmp_path / "outside"
    outside.write_bytes(b"external bytes never captured")
    archive = tmp_path / "backup.zip"
    portable.export_backup(store, archive)
    manifest, payloads = archive_parts(archive)
    assert manifest["version"] == 3
    assert manifest["symlinks"]["artifacts/reference"] == {"target": target}
    assert "workspace/artifacts/reference" not in payloads
    assert b"external bytes never captured" not in payloads.values()
    restored = portable.restore_backup(archive, tmp_path / "restore")
    assert not os.path.lexists(restored / "artifacts/reference")
    info = json.loads((restored / ".profile-info.json").read_text())
    assert info["inert_symlinks"]["artifacts/reference"] == {"target": target}
    second = tmp_path / "again.zip"
    portable.export_backup(JsonStore(restored), second)
    assert archive_parts(second)[0]["symlinks"] == manifest["symlinks"]
    assert outside.read_bytes() == b"external bytes never captured"
    assert link.is_symlink()


@pytest.mark.parametrize("bad_path", ["../escape", "threads/abc.json", "library-files/blobs/" + "0" * 64,
                                       "trash/reference", "active-profile.json", "artifacts/../escape"])
def test_inert_link_manifest_cannot_target_critical_paths_or_escape(tmp_path, bad_path):
    store, _ = new_source(tmp_path)
    archive = tmp_path / "valid.zip"
    portable.export_backup(store, archive)
    manifest, payloads = archive_parts(archive)
    manifest["version"] = 3
    manifest["symlinks"] = {bad_path: {"target": "../../outside"}}
    broken = write_archive(tmp_path / "broken.zip", manifest, payloads)
    root, marker = existing_profile(tmp_path)
    assert_failed_restore_preserved_selection(broken, root, marker)


@pytest.mark.parametrize("attack", ["payload_collision", "ancestor_collision", "nonstring", "nul", "zip_symlink"])
def test_link_metadata_and_unix_members_cannot_materialize_links(tmp_path, attack):
    store, _ = new_source(tmp_path)
    artifact = store.root / "artifacts" / "keep.txt"
    artifact.parent.mkdir()
    artifact.write_bytes(b"retained")
    archive = tmp_path / "valid.zip"
    portable.export_backup(store, archive)
    manifest, payloads = archive_parts(archive)
    manifest["version"] = 3
    modes = None
    if attack == "payload_collision":
        links = {"artifacts/keep.txt": {"target": "../../outside"}}
    elif attack == "ancestor_collision":
        links = {"artifacts": {"target": "../../outside"}}
    elif attack == "nonstring":
        links = {"artifacts/reference": {"target": 42}}
    elif attack == "nul":
        links = {"artifacts/reference": {"target": "x\x00y"}}
    else:
        links = {}
        modes = {"workspace/artifacts/keep.txt": stat.S_IFLNK | 0o777}
    manifest["symlinks"] = links
    broken = write_archive(tmp_path / "broken.zip", manifest, payloads, modes=modes)
    root, marker = existing_profile(tmp_path)
    assert_failed_restore_preserved_selection(broken, root, marker)
    assert artifact.read_bytes() == b"retained"


def test_hidden_business_files_and_extended_workspace_folders_are_not_omitted(tmp_path):
    store, _ = new_source(tmp_path)
    expected = {}
    for folder in ("artifacts", "imports", "Tool-Planung", "Workflow", "Zukunftsvisionen",
                   "Bilder", "grok-runtime", "handoffs", "authority-live-watch"):
        for suffix in (".private.env", ".git/history.bin", "nested/.retained"):
            p = store.root / folder / suffix
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes((folder + "/" + suffix).encode() + b"\x00\xff")
            expected[p.relative_to(store.root).as_posix()] = p.read_bytes()
    archive = tmp_path / "complete.zip"
    portable.export_backup(store, archive)
    manifest, payloads = archive_parts(archive)
    assert ".management.lock" not in manifest["files"]
    for name, body in expected.items():
        assert payloads["workspace/" + name] == body
    restored = portable.restore_backup(archive, tmp_path / "restore")
    for name, body in expected.items():
        assert (restored / name).read_bytes() == body


def test_directory_symlink_is_recorded_without_recursing_into_external_content(tmp_path):
    store, _ = new_source(tmp_path)
    outside = tmp_path / "external-dir"
    outside.mkdir()
    (outside / "private.txt").write_bytes(b"external bytes")
    artifact_dir = store.root / "artifacts"
    artifact_dir.mkdir()
    (artifact_dir / "linked-dir").symlink_to(outside, target_is_directory=True)
    archive = tmp_path / "complete.zip"
    portable.export_backup(store, archive)
    manifest, payloads = archive_parts(archive)
    assert manifest["symlinks"]["artifacts/linked-dir"]["target"] == str(outside)
    assert not any(name.startswith("workspace/artifacts/linked-dir") for name in payloads)
    restored = portable.restore_backup(archive, tmp_path / "restore")
    assert not os.path.lexists(restored / "artifacts/linked-dir")
    assert (outside / "private.txt").read_bytes() == b"external bytes"
    # The portable opt-in must not weaken the generic backup reader.
    with workspace_backup._SourceTree(store.root) as reader:
        with pytest.raises(BackupError):
            reader.scan(lambda _: True, lambda _: True)


@pytest.mark.parametrize("name,point_in_time", [("library-watch.json", True), ("handoff.json", False)])
def test_poller_snapshot_is_explicit_while_other_changes_refuse_publication(tmp_path, monkeypatch, name, point_in_time):
    store, _ = new_source(tmp_path)
    selected = store.root / name
    selected.write_bytes(b'{"generation":1}')
    reader = workspace_backup._SourceTree
    original_open = reader.open
    changed = False

    @contextmanager
    def update_after_pinned_read(self, relative, expected):
        nonlocal changed
        with original_open(self, relative, expected) as handle:
            yield handle
        if self.path.resolve() == store.root.resolve() and relative == name and not changed:
            changed = True
            selected.write_bytes(b'{"generation":222}')

    monkeypatch.setattr(reader, "open", update_after_pinned_read)
    archive = tmp_path / "snapshot.zip"
    if not point_in_time:
        with pytest.raises(BackupError):
            portable.export_backup(store, archive)
        assert not archive.exists()
    else:
        portable.export_backup(store, archive)
        manifest, payloads = archive_parts(archive)
        assert manifest["consistency"][name] == "point_in_time"
        assert payloads["workspace/" + name] == b'{"generation":1}'
        assert selected.read_bytes() == b'{"generation":222}'
    assert changed


def test_empty_business_directories_survive_with_private_permissions(tmp_path):
    store, _ = new_source(tmp_path)
    names = ["Bilder/empty", "Tool-Planung/Brainstormings", "Workflow/.private-empty"]
    for name in names:
        (store.root / name).mkdir(parents=True)
    archive = tmp_path / "directories.zip"
    portable.export_backup(store, archive)
    restored = portable.restore_backup(archive, tmp_path / "restore")
    for name in names:
        path = restored / name
        assert path.is_dir() and not path.is_symlink()
        assert list(path.iterdir()) == []
        assert stat.S_IMODE(path.stat().st_mode) == 0o700


def test_corrupted_completed_zip_is_never_published_as_verified(tmp_path, monkeypatch):
    store, _ = new_source(tmp_path)
    close = zipfile.ZipFile.close
    damaged = False

    def corrupt_after_close(self):
        nonlocal damaged
        writing = self.mode == "w" and self.fp is not None
        result = close(self)
        if writing and not damaged and self.filename:
            damaged = True
            with Path(self.filename).open("r+b") as handle:
                handle.write(b"BROKEN!!")
        return result

    monkeypatch.setattr(zipfile.ZipFile, "close", corrupt_after_close)
    destination = tmp_path / "published.zip"
    with pytest.raises(BackupError):
        portable.export_backup(store, destination)
    assert damaged
    assert not destination.exists()
    assert JsonStore(store.root).list_threads(True)[0].title == "Original project"


@pytest.mark.parametrize("attack", ["escape", "file_overlap", "link_overlap", "directory_alias"])
def test_directory_metadata_cannot_escape_or_collide_with_files_and_links(tmp_path, attack):
    store, thread = new_source(tmp_path)
    archive = tmp_path / "valid.zip"
    portable.export_backup(store, archive)
    manifest, payloads = archive_parts(archive)
    manifest["version"] = 3
    if attack == "escape":
        directories = ["../../escape"]
    elif attack == "file_overlap":
        directories = ["threads/" + thread.id + ".json"]
    elif attack == "link_overlap":
        directories = ["artifacts/link/child"]
        manifest["symlinks"] = {"artifacts/link": {"target": "../../external"}}
    else:
        directories = ["artifacts/One", "artifacts/one"]
    manifest["directories"] = directories
    broken = write_archive(tmp_path / "broken.zip", manifest, payloads)
    root, marker = existing_profile(tmp_path)
    assert_failed_restore_preserved_selection(broken, root, marker)
    assert not (tmp_path / "escape").exists()


def test_sqlite_backup_retains_inert_artifact_link_and_database_snapshot(tmp_path):
    store, thread = new_source(tmp_path, SQLiteStore)
    artifacts = store.root / "artifacts"
    artifacts.mkdir()
    (artifacts / "reference").symlink_to("../../external")
    archive = tmp_path / "sqlite.zip"
    try:
        portable.export_backup(store, archive)
        restored_path = portable.restore_backup(archive, tmp_path / "restore")
        assert not os.path.lexists(restored_path / "artifacts/reference")
        assert json.loads((restored_path / ".profile-info.json").read_text())["inert_symlinks"]["artifacts/reference"] == {"target": "../../external"}
        restored = SQLiteStore(restored_path)
        try:
            assert restored.get_thread(thread.id).context.notes == "Original notes remain"
        finally:
            restored.connection.close()
    finally:
        store.connection.close()


@pytest.mark.parametrize("relative", ["artifacts/" + "/".join(["a"] * 1500),
                                      "artifacts/" + "x" * 300,
                                      "artifacts/" + "/".join(["x" * 200] * 30)])
def test_unbounded_archive_paths_are_rejected_during_inspection(tmp_path, relative):
    store, _ = new_source(tmp_path)
    valid = tmp_path / "valid.zip"
    portable.export_backup(store, valid)
    manifest, payloads = archive_parts(valid)
    manifest["files"][relative] = {"size": 1, "sha256": hashlib.sha256(b"x").hexdigest()}
    payloads["workspace/" + relative] = b"x"
    broken = write_archive(tmp_path / "deep.zip", manifest, payloads)
    with pytest.raises(BackupError):
        portable.inspect_backup(broken)
    root, marker = existing_profile(tmp_path)
    assert_failed_restore_preserved_selection(broken, root, marker)


def test_forged_small_central_directory_count_is_not_trusted(tmp_path):
    store, _ = new_source(tmp_path)
    archive = tmp_path / "valid.zip"
    portable.export_backup(store, archive)
    body = bytearray(archive.read_bytes())
    end = body.rfind(b"PK\x05\x06")
    assert end >= 0
    body[end + 8:end + 12] = (1).to_bytes(2, "little") * 2
    hostile = tmp_path / "forged-count.zip"
    hostile.write_bytes(body)
    with pytest.raises(BackupError):
        portable.inspect_backup(hostile)
    root, marker = existing_profile(tmp_path)
    assert_failed_restore_preserved_selection(hostile, root, marker)


@pytest.mark.parametrize("attack", [None, "locator", "multipart", "count"])
def test_zip64_directory_layout_is_checked_before_restore(tmp_path, attack):
    import struct

    store, thread = new_source(tmp_path)
    archive = tmp_path / "valid.zip"
    portable.export_backup(store, archive)
    body = archive.read_bytes()
    end_offset = body.rfind(b"PK\x05\x06")
    end = struct.unpack_from("<4s4H2LH", body, end_offset)
    count, directory_size, directory_start = end[4], end[5], end[6]
    zip64 = struct.pack("<4sQ2H2L4Q", b"PK\x06\x06", 44, 45, 45, 0, 0,
                        count, count, directory_size, directory_start)
    locator = struct.pack("<4sLQL", b"PK\x06\x07", 0,
                          len(body) + 1000 if attack == "locator" else end_offset, 1)
    if attack == "multipart":
        locator = struct.pack("<4sLQL", b"PK\x06\x07", 1, end_offset, 2)
    if attack == "count":
        zip64 = struct.pack("<4sQ2H2L4Q", b"PK\x06\x06", 44, 45, 45, 0, 0,
                            1, 1, directory_size, directory_start)
    classic = struct.pack("<4s4H2LH", b"PK\x05\x06", 0, 0, 65535, 65535,
                          0xffffffff, 0xffffffff, 0)
    converted = tmp_path / "zip64.zip"
    converted.write_bytes(body[:end_offset] + zip64 + locator + classic)
    if attack:
        with pytest.raises(BackupError):
            portable.inspect_backup(converted)
        root, marker = existing_profile(tmp_path)
        assert_failed_restore_preserved_selection(converted, root, marker)
    else:
        assert portable.inspect_backup(converted)["verified"] is True
        restored = portable.restore_backup(converted, tmp_path / "restored")
        assert JsonStore(restored).get_thread(thread.id).context.notes == "Original notes remain"


def test_legacy_bytes_wrapper_fails_clearly_without_truncating_large_output(tmp_path, monkeypatch):
    store, _ = new_source(tmp_path)
    monkeypatch.setattr(portable, "LEGACY_LIMIT", 128)
    with pytest.raises(BackupError, match="legacy bytes limit"):
        portable.download_backup(store)
    archive = tmp_path / "path-still-works.zip"
    assert portable.export_backup(store, archive)["verified"] is True


@pytest.mark.parametrize("child", [None, "records", "blobs"])
def test_empty_library_directories_preserve_only_observed_source_structure(tmp_path, child):
    store, _ = new_source(tmp_path)
    library = store.root / "library-files"
    library.mkdir()
    expected = {"library-files"}
    if child:
        (library / child).mkdir()
        expected.add("library-files/" + child)
    archive = tmp_path / "empty-library.zip"
    portable.export_backup(store, archive)
    manifest, _ = archive_parts(archive)
    assert {name for name in manifest["directories"] if name.startswith("library-files")} == expected
    restored = portable.restore_backup(archive, tmp_path / "restore")
    actual = {"library-files"}
    actual.update("library-files/" + p.name for p in (restored / "library-files").iterdir())
    assert actual == expected
    assert all(p.is_dir() and not p.is_symlink() for p in (restored / "library-files").iterdir())


def test_legacy_direct_writer_stale_anchor_restores_business_fields_without_rewriting_archive(tmp_path):
    from types import SimpleNamespace

    from threaddesk.core.models import Thread

    store, thread = new_source(tmp_path)
    svc = ThreadService(store)
    prepared = store.get_thread(thread.id)
    prepared.description = "Historical operator coordination"
    prepared.status = "paused"
    prepared.context.files = ["design/original-reference.md"]
    prepared.context.prompts = [{"id": "historical", "text": "Keep this prompt"}]
    prepared.context.agent_state = {"codex": {"status": "done", "run_id": "historic-run"}}
    prepared.context.extra = {"review": {"decision": "retained", "source_ids": ["source-a"]}}
    store.save_thread(prepared)
    svc.snapshot("Before legacy direct write", thread.id)
    business_file = store.root / "artifacts" / "retained.bin"
    business_file.parent.mkdir()
    business_file.write_bytes(b"business payload\x00\xff\n")
    relative_thread = "threads/" + thread.id + ".json"
    relative_anchor = "thread-revisions/" + thread.id + ".json"
    thread_path = store.root / relative_thread
    anchor_path = store.root / relative_anchor
    original_anchor_bytes = anchor_path.read_bytes()
    anchor = json.loads(original_anchor_bytes)
    raw = json.loads(thread_path.read_bytes())
    assert raw["revision"] == anchor["revision"]

    # A legacy client writes known business fields directly, without updating
    # the newer revision anchor. Export must preserve these source bytes as-is.
    raw["context"]["notes"] = "Legacy writer changed notes without refreshing its anchor"
    assert Thread.from_dict(raw).to_dict() == raw
    legacy_bytes = json.dumps(raw, ensure_ascii=False, indent=2).encode()
    thread_path.write_bytes(legacy_bytes)
    assert anchor_path.read_bytes() == original_anchor_bytes
    archive = tmp_path / "legacy-direct-write.zip"
    portable.export_backup(SimpleNamespace(workspace_path=store.root), archive)
    manifest, payloads = archive_parts(archive)
    archive_before_restore = archive.read_bytes()
    assert payloads["workspace/" + relative_thread] == legacy_bytes
    assert payloads["workspace/" + relative_anchor] == original_anchor_bytes
    assert thread_path.read_bytes() == legacy_bytes
    assert anchor_path.read_bytes() == original_anchor_bytes

    restored = portable.restore_backup(archive, tmp_path / "isolated-restore")
    normalized = json.loads((restored / relative_thread).read_bytes())
    normalized_anchor = json.loads((restored / relative_anchor).read_bytes())
    assert normalized["revision"] == raw["revision"] + 1
    before_business = dict(raw)
    after_business = dict(normalized)
    before_business.pop("revision")
    after_business.pop("revision")
    assert after_business == before_business
    expected_digest = hashlib.sha256(json.dumps(after_business, sort_keys=True,
                                               ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    assert normalized_anchor == {"revision": normalized["revision"], "content_hash": expected_digest}
    assert normalized_anchor["content_hash"] != anchor["content_hash"]
    differences = {name for name in manifest["files"]
                   if (restored / name).read_bytes() != payloads["workspace/" + name]}
    assert differences == {relative_thread, relative_anchor}
    # The existing metadata reconciliation is idempotent and isolated.
    readback = JsonStore(restored).get_thread(thread.id)
    assert readback.to_dict() == normalized
    assert json.loads((restored / relative_anchor).read_bytes()) == normalized_anchor
    assert archive.read_bytes() == archive_before_restore
    assert thread_path.read_bytes() == legacy_bytes
    assert anchor_path.read_bytes() == original_anchor_bytes
    assert business_file.read_bytes() == b"business payload\x00\xff\n"
