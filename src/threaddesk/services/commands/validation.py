"""Bounded JSON Schema validation without external schema retrieval."""
from __future__ import annotations

import json
import hashlib
import math
import re
from jsonschema import Draft202012Validator
from referencing import Registry

from threaddesk.core.errors import ManagementError

ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
MAX_REQUEST = 1048576


def invalid(message="Invalid command request", **details):
    raise ManagementError("validation_error", message, **details)


def bounded(value, *, depth=0):
    if depth > 24:
        invalid("Command nesting exceeds its budget")
    if isinstance(value, dict):
        if len(value) > 10000 or any(not isinstance(key, str) for key in value):
            invalid("Invalid command object")
        for item in value.values():
            bounded(item, depth=depth + 1)
    elif isinstance(value, list):
        if len(value) > 10000:
            invalid("Command collection exceeds its budget")
        for item in value:
            bounded(item, depth=depth + 1)
    elif isinstance(value, float) and not math.isfinite(value):
        invalid("Non-finite numbers are not JSON values")
    elif value is not None and not isinstance(value, (str, bool, int, float)):
        invalid("Command must contain JSON values")


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def command_request_digest(workspace_id, command_id, arguments, operation_id, expected_revision=None):
    """Canonical identity shared by dispatch and owner receipt verification."""
    canonical = {"version": 1, "workspace_id": workspace_id, "command": command_id,
                 "arguments": arguments, "operation_id": operation_id,
                 "expected_revision": expected_revision}
    return hashlib.sha256(encode(canonical).encode()).hexdigest()


def validate(schema, arguments):
    # An empty registry has no network retrieval. Source-owned schemas cannot
    # make the command boundary fetch arbitrary URLs, even after extension.
    for error in Draft202012Validator(schema, registry=Registry()).iter_errors(arguments):
        invalid("Command arguments do not match the published schema",
                path="/".join(str(part) for part in error.absolute_path),
                validator=error.validator)


def envelope(request):
    bounded(request)
    if len(encode(request).encode()) > MAX_REQUEST:
        invalid("Command request exceeds its byte budget")
    if not isinstance(request, dict) or set(request) - {
        "version", "workspace_id", "command", "arguments", "operation_id", "expected_revision",
        "result_offset", "result_digest", "catalog_revision",
        "snapshot_at",
    }:
        invalid()
    if type(request.get("version")) is not int or request["version"] != 1:
        raise ManagementError("unsupported_version", "Command envelope version 1 is required")
    if not isinstance(request.get("arguments", {}), dict) or not isinstance(request.get("command"), str):
        invalid()
    if not isinstance(request.get("workspace_id"), str):
        invalid("An explicit workspace_id is required")
    if "operation_id" in request and (not isinstance(request["operation_id"], str) or not ID.fullmatch(request["operation_id"])):
        invalid("Invalid operation_id")
    if "expected_revision" in request and (type(request["expected_revision"]) is not int or request["expected_revision"] < 0):
        invalid("Invalid expected_revision")
    if type(request.get("result_offset", 0)) is not int or not 0 <= request.get("result_offset", 0) <= 100000000:
        invalid("Invalid result_offset")
    if "snapshot_at" in request and (not isinstance(request["snapshot_at"], str) or len(request["snapshot_at"]) > 64):
        invalid("Invalid snapshot_at")
    return dict(request)
