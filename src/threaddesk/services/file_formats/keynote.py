"""Conditional .key admission: a bounded, identified Keynote IWA ZIP only.

Private key material never becomes a presentation merely by its suffix.
Directory packages and older XML-only generations remain explicitly unsupported.
"""
from __future__ import annotations

import hashlib
import io
import os
from pathlib import PurePosixPath
import plistlib
import re
import stat
import struct
from time import monotonic
import unicodedata
from uuid import UUID
import zipfile
import zlib
from xml.parsers.expat import ExpatError

from threaddesk.core.errors import ManagementError
from threaddesk.services.file_formats.keynote_wire import KeynoteError, MAX_IWA, _need, fields, objects, one

MAX_CONTAINER = 256 * 1024 * 1024
MAX_ENTRIES = 2000
MAX_DIRECTORY = 1024 * 1024
MAX_EXPANDED = 512 * 1024 * 1024
MAX_INDEX_ZIP = 16 * 1024 * 1024
IDENTITY = "keynote_iwa_zip_v1"
_SECRET_MEMBER = re.compile(r"(?i)(^|[._-])(env|id_rsa|id_ed25519|credentials|cookies|secrets?)($|[._-])|\.(pem|key|p12|pfx|kdbx)$")


def _archive(stream, size, *, deadline=None):
    # Cap the central directory BEFORE ZipFile allocates an object per member.
    stream.seek(max(0, size - 65557))
    tail = stream.read(min(size, 65557))
    location = tail.rfind(b"PK\x05\x06")
    _need(location >= 0 and location + 22 <= len(tail))
    _, disk, start, count_disk, count, directory_size, offset, comment = struct.unpack_from("<4s4H2LH", tail, location)
    _need(disk == start == 0 and count == count_disk and 0 < count <= MAX_ENTRIES, "keynote_limit")
    _need(location + 22 + comment == len(tail) and directory_size <= MAX_DIRECTORY, "keynote_limit")
    _need(offset + directory_size <= size - len(tail) + location)
    stream.seek(offset)
    directory = stream.read(directory_size)
    cursor, actual = 0, 0
    while cursor < len(directory):
        _need(cursor + 46 <= len(directory) and directory[cursor:cursor + 4] == b"PK\x01\x02")
        name_size, extra_size, comment_size = struct.unpack_from("<3H", directory, cursor + 28)
        cursor += 46 + name_size + extra_size + comment_size
        actual += 1
        _need(actual <= MAX_ENTRIES and cursor <= len(directory), "keynote_limit")
    _need(actual == count)
    stream.seek(0)
    archive = zipfile.ZipFile(stream)
    seen, total = set(), 0
    try:
        for info in archive.infolist():
            _need(deadline is None or monotonic() <= deadline, "keynote_limit")
            name = info.filename
            _need(name == info.orig_filename)
            parts = PurePosixPath(name).parts
            _need(name and not name.startswith(("/", "\\")) and "\\" not in name and ":" not in name
                  and "\x00" not in name and len(name.encode()) <= 4096
                  and all(part not in {".", ".."} for part in parts))
            _need(not info.flag_bits & 1 and info.compress_type in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED})
            mode = stat.S_IFMT(info.external_attr >> 16)
            _need(mode in {0, stat.S_IFREG, stat.S_IFDIR})
            key = unicodedata.normalize("NFC", name.rstrip("/")).casefold()
            _need(key not in seen)
            seen.add(key)
            _need(info.file_size <= MAX_CONTAINER and info.compress_size <= MAX_CONTAINER, "keynote_limit")
            total += info.file_size
            _need(total <= MAX_EXPANDED, "keynote_limit")
            if not info.is_dir():
                _need(not _SECRET_MEMBER.search(PurePosixPath(name).name), "keynote_secret_member")
                # ZipFile checks local-vs-central names and header flags here,
                # without expanding large media assets.
                with archive.open(info):
                    pass
        return archive
    except BaseException:
        archive.close()
        raise


def _read(archive, name, maximum):
    info = archive.getinfo(name)
    _need(not info.is_dir() and info.file_size <= maximum, "keynote_limit")
    with archive.open(info) as incoming:
        body = incoming.read(maximum + 1)
    _need(len(body) == info.file_size and len(body) <= maximum, "keynote_limit")
    return body


def _index(archive, prefix, deadline):
    names = archive.namelist()
    document = prefix + "Index/Document.iwa"
    _need(document in names)
    slides = [name for name in names if name.startswith(prefix + "Index/")
              and re.fullmatch(r"(?:MasterSlide|TemplateSlide|Slide)(?:-[A-Za-z0-9_-]+)?\.iwa", PurePosixPath(name).name)]
    _need(slides, "keynote_identity_required")
    roots = [(identifier, kind, payload) for identifier, kind, payload in objects(_read(archive, document, MAX_IWA), deadline=deadline)
             if identifier == 1 and kind == 1]
    _need(len(roots) == 1, "keynote_identity_required")
    root = fields(roots[0][2])
    show = fields(one(root, 2, 2))
    _need(one(show, 1, 0) > 0 and one(root, 3, 2), "keynote_identity_required")
    _need(15 not in root, "keynote_identity_required")  # Pages requires field 15.
    # A second genuine IWA component prevents a fake ZIP name-only admission.
    _need(list(objects(_read(archive, sorted(slides)[0], MAX_IWA), deadline=deadline)), "keynote_identity_required")


def inspect_stream(stream, size):
    _need(0 < size <= MAX_CONTAINER, "keynote_limit")
    stream.seek(0)
    _need(stream.read(4) == b"PK\x03\x04", "keynote_identity_required")
    deadline = monotonic() + 1
    with _archive(stream, size, deadline=deadline) as archive:
        names = archive.namelist()
        candidates = {name[:-len("Metadata/Properties.plist")] for name in names if name.endswith("Metadata/Properties.plist")}
        _need(len(candidates) == 1, "keynote_identity_required")
        prefix = candidates.pop()
        _need(prefix == "" or len(PurePosixPath(prefix).parts) == 1)
        props = plistlib.loads(_read(archive, prefix + "Metadata/Properties.plist", 65536))
        _need(isinstance(props, dict) and isinstance(props.get("fileFormatVersion"), str)
              and re.fullmatch(r"[0-9][A-Za-z0-9._-]{0,63}", props["fileFormatVersion"]), "keynote_identity_required")
        _need(isinstance(props.get("documentUUID"), str), "keynote_identity_required")
        _need(UUID(props["documentUUID"]) == UUID(_read(archive, prefix + "Metadata/DocumentIdentifier", 128).decode().strip()))
        direct, inner = prefix + "Index/Document.iwa" in names, prefix + "Index.zip" in names
        _need(direct != inner, "keynote_identity_required")
        if direct:
            _index(archive, prefix, deadline)
        else:
            body = _read(archive, prefix + "Index.zip", MAX_INDEX_ZIP)
            with _archive(io.BytesIO(body), len(body), deadline=deadline) as index:
                _need(all(info.is_dir() or (info.filename.startswith("Index/") and info.filename.endswith(".iwa")) for info in index.infolist()))
                _index(index, "", deadline)
        return {"identity": IDENTITY, "version": 1, "container": "zip_iwa",
                "file_format_version": props["fileFormatVersion"], "index": False, "preview": False}


def inspect_keynote(path, *, expected_sha256=None, expected_size=None):
    """Bind format validation and byte identity to one no-follow descriptor."""
    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(descriptor, "rb") as incoming:
            descriptor = None
            before = os.fstat(incoming.fileno())
            _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size <= MAX_CONTAINER)
            digest, size = hashlib.sha256(), 0
            while True:
                body = incoming.read(1024 * 1024)
                if not body:
                    break
                size += len(body)
                _need(size <= MAX_CONTAINER, "keynote_limit")
                digest.update(body)
            hexdigest = digest.hexdigest()
            _need(expected_sha256 is None or hexdigest == expected_sha256, "keynote_integrity")
            _need(expected_size is None or size == expected_size, "keynote_integrity")
            result = inspect_stream(incoming, size)
            after = os.fstat(incoming.fileno())
            stamp = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_ctime_ns)
            _need(stamp(before) == stamp(after), "keynote_integrity")
            return {**result, "sha256": hexdigest, "size": size}
    except KeynoteError:
        raise
    except (OSError, ValueError, TypeError, KeyError, struct.error, zipfile.BadZipFile,
            zipfile.LargeZipFile, zlib.error, ExpatError, EOFError, OverflowError, RuntimeError) as exc:
        raise KeynoteError() from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def validation_matches(record):
    proof = record.get("content_validation") or {}
    return (isinstance(proof, dict) and proof.get("identity") == IDENTITY and proof.get("version") == 1
            and proof.get("sha256") == record.get("sha256") and proof.get("size") == record.get("size"))


def require_validated_keynote(record, path):
    if PurePosixPath(record["filename"]).suffix.casefold() != ".key":
        return None
    if not validation_matches(record):
        raise ManagementError("keynote_validation_required", "Keynote opening requires validated presentation bytes.")
    try:
        return inspect_keynote(path, expected_sha256=record["sha256"], expected_size=record["size"])
    except KeynoteError as exc:
        raise ManagementError(exc.code, "Keynote presentation identity could not be confirmed.") from exc
