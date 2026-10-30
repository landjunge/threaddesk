"""Bounded declarative module command contracts; no executable imports."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from threaddesk.core.errors import InvalidState

CAPABILITIES = frozenset({"read_nodes", "read_thread", "read_whiteboard",
                          "append_whiteboard", "read_own_data", "write_own_record"})
MAX_COMMANDS = 64
LOCAL_ID = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
DECLARATION_FIELDS = {"id", "capability", "description", "input_schema", "action", "required_approvals"}
SCHEMA_KEYWORDS = {"type", "properties", "required", "additionalProperties", "enum", "const",
                   "items", "minItems", "maxItems", "minLength", "maxLength", "minimum", "maximum",
                   "minProperties", "maxProperties", "allOf", "anyOf", "oneOf", "not"}


def _restricted_schema(schema, *, depth=0, count=None):
    count = [0] if count is None else count
    count[0] += 1
    if depth > 8 or count[0] > 200 or not isinstance(schema, dict) or set(schema) - SCHEMA_KEYWORDS:
        raise InvalidState("module_command_schema")
    for key, value in schema.items():
        if key == "properties":
            if not isinstance(value, dict) or len(value) > 50:
                raise InvalidState("module_command_schema")
            for child in value.values():
                _restricted_schema(child, depth=depth + 1, count=count)
        elif key in {"items", "not"} or key == "additionalProperties" and isinstance(value, dict):
            _restricted_schema(value, depth=depth + 1, count=count)
        elif key in {"allOf", "anyOf", "oneOf"}:
            if not isinstance(value, list) or len(value) > 16:
                raise InvalidState("module_command_schema")
            for child in value:
                _restricted_schema(child, depth=depth + 1, count=count)


@lru_cache(maxsize=128)
def _checked_schema(encoded):
    # Discovery reloads current manifests to honor revocation. Cache only the
    # pure schema check by its exact bytes, never enablement or permissions.
    schema = json.loads(encoded)
    _restricted_schema(schema)
    Draft202012Validator.check_schema(schema)


def validate_declarations(manifest):
    if not isinstance(manifest.commands, (tuple, list)) or len(manifest.commands) > MAX_COMMANDS:
        raise InvalidState("module_command_limit")
    seen = set()
    for item in manifest.commands:
        if (not isinstance(item, dict) or set(item) - DECLARATION_FIELDS
                or not {"id", "capability"} <= set(item)):
            raise InvalidState("module_command_declaration")
        identity, capability = item["id"], item["capability"]
        if (not isinstance(identity, str) or len(identity) > 64 or not LOCAL_ID.fullmatch(identity)
                or identity in seen or not isinstance(capability, str) or capability not in CAPABILITIES):
            raise InvalidState("module_command_identity")
        seen.add(identity)
        if not isinstance(item.get("description", ""), str) or len(item.get("description", "")) > 500:
            raise InvalidState("module_command_description")
        if capability == "write_own_record":
            if not isinstance(item.get("action"), str) or not 1 <= len(item["action"]) <= 128:
                raise InvalidState("module_command_action")
        elif "action" in item:
            raise InvalidState("module_command_action")
        approvals = item.get("required_approvals", [])
        if (not isinstance(approvals, (tuple, list)) or len(approvals) > 32
                or any(not isinstance(value, str) or not value or len(value) > 128 for value in approvals)
                or len(set(approvals)) != len(approvals)):
            raise InvalidState("module_command_approvals")
        if "input_schema" in item:
            schema = item["input_schema"]
            try:
                encoded = json.dumps(schema, allow_nan=False, sort_keys=True)
                if len(encoded.encode()) > 8192:
                    raise InvalidState("module_command_schema")
                _checked_schema(encoded)
            except (TypeError, ValueError, SchemaError) as exc:
                raise InvalidState("module_command_schema") from exc


