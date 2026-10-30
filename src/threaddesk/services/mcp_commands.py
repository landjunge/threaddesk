"""Live MCP views of the source-owned command registry, without a second dispatcher."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import re

from threaddesk.core.errors import ManagementError
from threaddesk.services.commands.schemas import ID, REV, TEXT, obj
from threaddesk.services.commands.validation import bounded, encode, validate, MAX_REQUEST, invalid

PREFIX = "td_"


def tool_name(command_id):
    """Keep valid names readable and stable, including long module identities."""
    # KiraBridge's existing native call contract accepts 64 ASCII characters
    # and no dots. Escape underscores as well, so a.b and a_b stay distinct.
    escaped = "".join("__" if char == "." else "_u" if char == "_" else char
                      if re.fullmatch(r"[A-Za-z0-9-]", char)
                      else "_x" + char.encode().hex() + "_" for char in command_id)
    name = PREFIX + escaped
    if len(name) <= 64:
        return name
    return PREFIX + escaped[:20] + "_" + hashlib.sha256(command_id.encode()).hexdigest()[:40]


def input_schema(spec):
    domain = deepcopy(spec.schema)
    # A nested schema without its own resource identity would resolve #/$defs,
    # #anchors and recursive # references against the MCP envelope. Preserve its
    # original resource root, including any source-owned $id and anchor scope.
    if domain.get("$id") in (None, "", "#"):
        domain["$id"] = "urn:threaddesk:mcp-command:" + hashlib.sha256(spec.id.encode()).hexdigest()
    fields = {"workspace_id": TEXT, "arguments": domain,
              "operation_id": ID, "expected_revision": REV,
              "catalog_revision": TEXT, "result_offset": REV,
              "result_digest": TEXT, "snapshot_at": TEXT}
    required = ["workspace_id", "arguments"]
    if spec.effect != "read":
        required.append("operation_id")
        if spec.revision_target:
            required.append("expected_revision")
        # CommandApplication injects native operation/CAS bindings before domain
        # validation. Publish them once in the envelope, retaining optional
        # domain copies so the shared dispatcher can reject mismatches.
        if spec.native_contract:
            for field in ("operation_id", "expected_revision"):
                if field not in domain.get("properties", {}):
                    continue
                # Keep references in a lifted field in the domain resource too.
                fields[field] = {"$ref": domain["$id"].removesuffix("#") + "#/properties/" + field}
                if field in domain.get("required", []):
                    domain["required"].remove(field)
                    if field not in required:
                        required.append(field)
    return deepcopy(obj(fields, required))


class McpCommands:
    def __init__(self, application):
        self.application = application

    def _records(self):
        app = self.application
        return app.registry.records(app.scopes, "mcp")

    def _names(self, records):
        names = {}
        for row in records:
            name = tool_name(row["id"])
            if name in names:
                raise ManagementError("command_conflict", "Commands have conflicting MCP names")
            names[name] = row["id"]
        return names

    def list_tools(self):
        app = self.application
        records = self._records()
        self._names(records)
        result = []
        for row in records:
            if row["availability"] != "available":
                continue
            spec = app.registry.specs[row["id"]]
            read = spec.effect == "read"
            result.append({
                "name": tool_name(spec.id), "description": spec.description,
                "inputSchema": input_schema(spec),
                "annotations": {"readOnlyHint": read, "destructiveHint": not read,
                                "idempotentHint": not read, "openWorldHint": not read},
                "_meta": {"threaddesk": {**deepcopy(row), "workspace_id": app.workspace_id}},
            })
        return result

    def revision(self):
        app = self.application
        return app.registry.revision(app.scopes, "mcp")

    def call(self, name, arguments):
        app = self.application
        identity = self._names(self._records()).get(name)
        if identity is None:
            raise ManagementError("command_not_found", "MCP command is no longer registered")
        spec = app.registry.get(identity)
        # Bound the wrapper before schema iteration, then leave all authority,
        # exact domain validation, CAS, receipts and effects to the application.
        bounded(arguments)
        if len(encode(arguments).encode()) > MAX_REQUEST:
            invalid("Command request exceeds its byte budget")
        validate(input_schema(spec), arguments)
        request = {"version": 1, "command": identity, **arguments}
        return app.call(request, read_only=spec.effect == "read")
