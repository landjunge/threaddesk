"""Validation shared by all file-domain transports."""
from __future__ import annotations

from pathlib import PurePosixPath
import re

from threaddesk.services.library_files.state import fail

ID = re.compile(r"^[0-9a-f]{12}$")
OPERATION = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
FIELDS = {
    "rename": {"filename"}, "copy": {"filename", "folder", "thread_id", "node_ids"},
    "move": {"folder", "thread_id", "node_ids"}, "assign": {"thread_id", "node_ids"},
    "trash": set(), "restore": {"trash_generation"},
}


def record_id(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        fail("validation_error", "Exakte Datei-ID erforderlich.")
    return value


def operation_id(value):
    if not isinstance(value, str) or not OPERATION.fullmatch(value):
        fail("validation_error", "Ungültige Operationskennung.")
    return value


def filename(value):
    if (not isinstance(value, str) or not value or value in {".", ".."}
            or len(value.encode("utf-8")) > 240
            or any(ord(c) < 32 or ord(c) == 127 or c in '/\\:' for c in value)):
        fail("validation_error", "Ungültiger Dateiname.")
    return value


def folder(value):
    if not isinstance(value, str) or len(value.encode("utf-8")) > 2000:
        fail("validation_error", "Ungültiger Ordner.")
    if value == "":
        return ""
    if (value.startswith("/") or "\\" in value or ":" in value
            or any(ord(c) < 32 or ord(c) == 127 for c in value)
            or any(part in {"", ".", ".."} for part in value.split("/"))):
        fail("validation_error", "Nur relative Bibliotheksordner sind erlaubt.")
    return PurePosixPath(value).as_posix()


def request(arguments):
    if (not isinstance(arguments, dict)
            or set(arguments) != {"operation_id", "action", "id", "expected_revision", "data"}):
        fail("validation_error", "Ungültige Dateianfrage.")
    operation_id(arguments["operation_id"])
    record_id(arguments["id"])
    revision = arguments["expected_revision"]
    if type(revision) is not int or revision < 1:
        fail("validation_error", "Positive erwartete Dateirevision erforderlich.")
    action, data = arguments["action"], arguments["data"]
    if action not in FIELDS or not isinstance(data, dict) or set(data) - FIELDS[action]:
        fail("validation_error", "Unbekannte Dateiaktion oder Aktionsfelder.")
    if action == "rename" and set(data) != {"filename"}:
        fail("validation_error", "Neuer Dateiname erforderlich.")
    if action in {"assign", "move"} and not data:
        fail("validation_error", "Mindestens eine Zuordnung erforderlich.")
    if action == "restore" and set(data) != {"trash_generation"}:
        fail("validation_error", "Papierkorbgeneration erforderlich.")
    if "filename" in data:
        filename(data["filename"])
    if "folder" in data:
        folder(data["folder"])
    if "thread_id" in data and data["thread_id"] is not None:
        record_id(data["thread_id"])
    if "node_ids" in data:
        values = data["node_ids"]
        if not isinstance(values, list) or len(values) > 100 or len(set(map(str, values))) != len(values):
            fail("validation_error", "Höchstens 100 eindeutige Knoten-IDs erforderlich.")
        for identity in values:
            record_id(identity)
    if "trash_generation" in data:
        if type(data["trash_generation"]) is not int or data["trash_generation"] < 1:
            fail("validation_error", "Ungültige Papierkorbgeneration.")
    return arguments
