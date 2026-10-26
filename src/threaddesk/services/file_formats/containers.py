"""Read bounded document containers; never extract members onto the filesystem."""

from __future__ import annotations

import gzip
import tarfile
import xml.etree.ElementTree as ET
import zipfile
from io import BytesIO
from pathlib import PurePosixPath

from .text import decode, html_text

MAX_MEMBERS = 2000
MAX_MEMBER_BYTES = 2 * 1024 * 1024
MAX_EXPANDED_BYTES = 8 * 1024 * 1024


def _safe_name(name):
    parts = PurePosixPath(name.replace("\\", "/"))
    return not parts.is_absolute() and ".." not in parts.parts and "\x00" not in name


def _xml_text(raw):
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("xml_entities_forbidden")
    return " ".join(value for value in ET.fromstring(raw).itertext() if value.strip())


def zip_text(raw: bytes, *, epub=False) -> tuple[str, bool]:
    values = []
    total = 0
    truncated = False
    with zipfile.ZipFile(BytesIO(raw)) as archive:
        members = archive.infolist()
        if len(members) > MAX_MEMBERS:
            raise ValueError("archive_member_limit")
        for item in members:
            name = item.filename
            wanted = (
                name.endswith((".xhtml", ".html", ".htm"))
                if epub
                else (
                    name == "content.xml"
                    or name.startswith("word/")
                    and name.endswith(".xml")
                    or name.startswith("xl/")
                    and name.endswith(".xml")
                    or name.startswith("ppt/slides/")
                    and name.endswith(".xml")
                )
            )
            if not wanted or item.is_dir():
                continue
            if not _safe_name(name) or item.flag_bits & 1:
                raise ValueError("archive_unsafe_or_encrypted")
            if (
                item.file_size > MAX_MEMBER_BYTES
                or total + item.file_size > MAX_EXPANDED_BYTES
            ):
                truncated = True
                continue
            total += item.file_size
            payload = archive.read(item)
            values.append(html_text(payload) if epub else _xml_text(payload))
    return "\n".join(values), truncated


def archive_text(raw: bytes, filename: str) -> tuple[str, bool]:
    suffix = PurePosixPath(filename).suffix.casefold()
    if suffix == ".zip":
        with zipfile.ZipFile(BytesIO(raw)) as archive:
            infos = archive.infolist()
            return "\n".join(
                item.filename
                for item in infos[:MAX_MEMBERS]
                if _safe_name(item.filename)
            ), len(infos) > MAX_MEMBERS
    if suffix in {".tar", ".tgz"}:
        names = []
        expanded = 0
        with tarfile.open(fileobj=BytesIO(raw), mode="r|*") as archive:
            for index, member in enumerate(archive):
                if index >= MAX_MEMBERS:
                    return "\n".join(names), True
                if _safe_name(member.name):
                    names.append(member.name)
                expanded += member.size
                if member.size > MAX_MEMBER_BYTES or expanded > MAX_EXPANDED_BYTES:
                    # Advancing a streaming tar would otherwise decompress
                    # and skip the entire (possibly enormous) member body.
                    return "\n".join(names), True
        return "\n".join(names), False
    with gzip.GzipFile(fileobj=BytesIO(raw)) as stream:
        payload = stream.read(MAX_MEMBER_BYTES + 1)
    return decode(payload[:MAX_MEMBER_BYTES]), len(payload) > MAX_MEMBER_BYTES
