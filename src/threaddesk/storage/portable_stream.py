"""Bounded I/O and inert link inventory for the existing portable backup."""
from __future__ import annotations

import hashlib
import io
import os
import stat
import struct
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

from threaddesk.storage.workspace_backup import (
    BackupError,
    _relative,
    _SourceTree,
    _stamp,
)

CHUNK_SIZE = 1024 * 1024
FLEX_DIRS = frozenset({'artifacts', 'imports', 'Tool-Planung', 'Workflow', 'Zukunftsvisionen', 'Bilder'})


def limits(max_bytes, max_files, max_manifest_bytes):
    if any(type(value) is not int or value < 1 for value in (max_bytes, max_files, max_manifest_bytes)):
        raise BackupError('Backup limits must be positive integers.')


def safe_relative(name):
    if (not isinstance(name, str) or len(name.encode('utf-8')) > 4096
            or len(name.split('/')) > 256 or any(len(part.encode('utf-8')) > 255 for part in name.split('/'))):
        raise BackupError('Backup path exceeds the portable path budget.')
    return _relative(name, portable=True)


def link_path(name):
    parts = safe_relative(name)
    return len(parts) > 1 and parts[0] in FLEX_DIRS


def checked_links(links):
    if not isinstance(links, dict):
        raise BackupError('Invalid inert link metadata.')
    for name, value in links.items():
        if (not link_path(name) or not isinstance(value, dict) or set(value) != {'target'}
                or not isinstance(value['target'], str) or not value['target']
                or '\x00' in value['target'] or len(value['target'].encode('utf-8')) > 32768):
            raise BackupError('Invalid inert link metadata.')
    return links


def scan(tree, allowed, descend, *, max_entries):
    """Opt-in POSIX metadata capture; strict SourceTree defaults are untouched.

    Native Windows retains its existing fail-closed reparse-point handling.
    Neither platform follows a link. Only explicitly noncanonical data trees
    may carry inert POSIX link metadata; root aliases and store links fail.
    """
    if not hasattr(tree, '_parent'):
        files = tree.scan(allowed, descend)
        if len(files) > max_entries:
            raise BackupError('Backup exceeds the file limit.')
        return files, {}, dict(tree.directories)
    files, links, directories = {}, {}, {}
    entries = 0

    def walk(parts):
        nonlocal entries
        with tree._parent(parts) as directory:
            for name in sorted(os.listdir(directory)):
                relative = '/'.join((*parts, name))
                selected, recurse = allowed(relative), descend(relative)
                if not selected and not recurse:
                    continue
                entries += 1
                if entries > max_entries:
                    raise BackupError('Backup exceeds the file limit.')
                before = os.stat(name, dir_fd=directory, follow_symlinks=False)
                expected = _stamp(before)
                if stat.S_ISLNK(before.st_mode):
                    if not link_path(relative):
                        raise BackupError('Symbolic link in canonical backup data: ' + relative)
                    target = os.readlink(name, dir_fd=directory)
                    if _stamp(os.stat(name, dir_fd=directory, follow_symlinks=False)) != expected:
                        raise BackupError('Backup link changed during capture: ' + relative)
                    checked_links({relative: {'target': target}})
                    links[relative] = {'target': target, 'stamp': expected}
                elif stat.S_ISDIR(before.st_mode):
                    if recurse:
                        identity = expected[:2]
                        if tree.directories.setdefault(relative, identity) != identity:
                            raise BackupError('Backup directory changed during capture.')
                        directories[relative] = expected
                        walk((*parts, name))
                elif selected:
                    if not stat.S_ISREG(before.st_mode):
                        raise BackupError('Backup source contains a nonregular file: ' + relative)
                    files[relative] = expected
    walk(())
    return files, links, directories


def copy_hash(incoming, outgoing=None, *, limit):
    digest, size = hashlib.sha256(), 0
    while True:
        chunk = incoming.read(min(CHUNK_SIZE, max(1, limit - size + 1)))
        if not chunk:
            break
        size += len(chunk)
        if size > limit:
            raise BackupError('Backup exceeds the size limit.')
        digest.update(chunk)
        if outgoing is not None:
            outgoing.write(chunk)
    return {'size': size, 'sha256': digest.hexdigest()}


def preflight_zip(handle, size, *, max_files, max_manifest_bytes):
    """Bound central-directory allocation before ZipFile constructs ZipInfos."""
    if size < 22:
        raise BackupError('Invalid ZIP end record.')
    handle.seek(max(0, size - 65557))
    tail = handle.read(min(size, 65557))
    position = tail.rfind(b'PK\x05\x06')
    while position >= 0:
        if len(tail) >= position + 22:
            end = struct.unpack_from('<4s4H2LH', tail, position)
            if position + 22 + end[-1] == len(tail):
                break
        position = tail.rfind(b'PK\x05\x06', 0, position)
    if position < 0:
        raise BackupError('Invalid ZIP end record.')
    _, disk, directory_disk, disk_count, count, directory_size, directory_start, _ = end
    end_start = size - len(tail) + position
    if disk or directory_disk or disk_count != count:
        raise BackupError('Multipart ZIP backups are not supported.')
    if count == 65535 or directory_size == 0xffffffff or directory_start == 0xffffffff:
        if end_start < 20:
            raise BackupError('Invalid ZIP64 locator.')
        handle.seek(end_start - 20)
        locator = handle.read(20)
        signature, disk, offset, disks = struct.unpack('<4sLQL', locator)
        # Exactly 65535 entries also fits the classic format without ZIP64.
        classic_max_count = signature != b'PK\x06\x07' and directory_size != 0xffffffff and directory_start != 0xffffffff
        if not classic_max_count and (signature != b'PK\x06\x07' or disk or disks != 1 or offset > end_start - 76):
            raise BackupError('Invalid ZIP64 locator.')
        if not classic_max_count:
            handle.seek(offset)
            raw = handle.read(56)
            if len(raw) != 56:
                raise BackupError('Invalid ZIP64 end record.')
            signature, record_size, _, _, disk, directory_disk, disk_count, count, directory_size, directory_start = struct.unpack('<4sQ2H2L4Q', raw)
            if (signature != b'PK\x06\x06' or record_size < 44 or offset + 12 + record_size != end_start - 20
                    or disk or directory_disk or disk_count != count):
                raise BackupError('Invalid ZIP64 end record.')
            end_start = offset
    if (count > max_files or directory_size > max_manifest_bytes + max_files * 128
            or directory_start + directory_size > end_start):
        raise BackupError('ZIP central directory exceeds the backup budget.')
    # Do not trust a forged small EOCD count: count fixed central records before
    # ZipFile can allocate Python objects for every advertised filename.
    cursor, actual_count = directory_start, 0
    directory_end = directory_start + directory_size
    while cursor < directory_end:
        handle.seek(cursor)
        header = handle.read(46)
        if len(header) != 46 or header[:4] != b'PK\x01\x02':
            raise BackupError('Invalid ZIP central directory record.')
        lengths = struct.unpack_from('<HHH', header, 28)
        cursor += 46 + sum(lengths)
        actual_count += 1
        if cursor > directory_end or actual_count > max_files:
            raise BackupError('ZIP central directory exceeds the backup budget.')
    if actual_count != count:
        raise BackupError('ZIP central directory count does not match.')
    handle.seek(0)


@contextmanager
def input_file(source, *, limit):
    """Pin path inputs through the existing no-follow source boundary."""
    if isinstance(source, bytes):
        if len(source) > limit:
            raise BackupError('Backup exceeds the size limit.')
        with io.BytesIO(source) as handle:
            yield handle, len(source)
    elif isinstance(source, (str, os.PathLike)):
        path = Path(source).absolute()
        with _SourceTree(path.parent) as tree:
            expected = tree.info(path.name)
            if expected[3] > limit:
                raise BackupError('Backup exceeds the size limit.')
            with tree.open(path.name, expected) as handle:
                yield handle, expected[3]
    elif hasattr(source, 'read') and hasattr(source, 'seek'):
        position = source.tell()
        source.seek(0, os.SEEK_END)
        size = source.tell()
        if size > limit:
            raise BackupError('Backup exceeds the size limit.')
        source.seek(0)
        try:
            yield source, size
        finally:
            source.seek(position)
    else:
        raise BackupError('Backup requires bytes, a regular path or a seekable file.')


def check_member_names(files, symlinks, directories=(), *, legacy_case_sensitive=False):
    """No aliases, parent/file collisions or descendants of inert links."""
    seen = {}
    for name in (*files, *symlinks, *directories):
        safe_relative(name)
        folded = name if legacy_case_sensitive else name.casefold()
        if folded in seen:
            raise BackupError('Colliding backup paths.')
        seen[folded] = name
    leaves = {name if legacy_case_sensitive else name.casefold() for name in (*files, *symlinks)}
    for name in seen:
        if any((parent.as_posix() if legacy_case_sensitive else parent.as_posix().casefold()) in leaves
               for parent in PurePosixPath(name).parents if parent.as_posix() != '.'):
            raise BackupError('Overlapping backup paths.')
