"""Revision-bound view delivery with a real client acknowledgement boundary.

Persisting an apply intent never claims a visible camera change. A private
client capability and observed view state distinguish delivery from queueing.
No method records file activity or performs a file/domain mutation.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import hmac
import json
from uuid import uuid4

from threaddesk.core.errors import ManagementError
from threaddesk.core.models import now_iso
from threaddesk.services.activity import utc
from threaddesk.services.graph_state import GraphDocument
from threaddesk.services.graph_views import GraphViewService, _identity
from threaddesk.services.graph_view_observation import observe

CLIENT_LEASE = 90
INTENT_TTL = 15 * 60


def _initial():
    return {"schema_version": 1, "clients": {}, "requests": {}}


def _request(arguments):
    if (not isinstance(arguments, dict) or set(arguments) - {"id", "expected_revision", "operation_id", "client_id"}
            or not {"id", "expected_revision", "operation_id"} <= set(arguments)):
        raise ManagementError("validation_error", "Invalid graph view apply request.")
    args = deepcopy(arguments)
    _identity(args["id"]);_identity(args["operation_id"])
    if "client_id" in args:
        _identity(args["client_id"])
    if type(args["expected_revision"]) is not int or args["expected_revision"] < 1:
        raise ManagementError("validation_error", "An exact saved-view revision is required.")
    digest = hashlib.sha256(json.dumps(args, sort_keys=True).encode()).hexdigest()
    return args, digest


def _age(stamp):
    return (datetime.now(timezone.utc) - utc(stamp)).total_seconds()


class GraphViewControlService:
    def __init__(self, store):
        self.document = GraphDocument(store, "graph-view-control.json", _initial)
        self.views = GraphViewService(store)

    def _read(self):
        data = self.document.read()
        if not isinstance(data.get("clients"), dict) or not isinstance(data.get("requests"), dict):
            raise ManagementError("graph_state_unavailable", "Graph view delivery state is invalid.")
        return data

    @staticmethod
    def _public_client(client):
        return {"client_id": client["client_id"], "connected_at": client["connected_at"],
                "last_seen": client["last_seen"], "active": 0 <= _age(client["last_seen"]) <= CLIENT_LEASE}

    def clients(self):
        return {"clients": [self._public_client(client) for client in self._read()["clients"].values()]}

    def reset_runtime(self):
        """A server restart invalidates transport leases and pending intents."""
        with self.document.locked():
            data = self._read()
            changed = bool(data["clients"])
            data["clients"] = {}
            cancelled = 0
            for request in data["requests"].values():
                if not request.get("acknowledgement"):
                    request["acknowledgement"] = {"status": "cancelled_restart", "observed_at": now_iso(),
                                                  "kind": "runtime_invalidation", "client_id": None,
                                                  "error_code": "runtime_restarted", "observation": None}
                    cancelled += 1
            if changed or cancelled:
                self.document.write(data)
            return {"cancelled": cancelled, "client_leases_invalidated": changed}

    @staticmethod
    def _authenticate(data, client_id, token):
        _identity(client_id)
        client = data["clients"].get(client_id)
        if (not client or not isinstance(token, str) or len(token) != 64
                or not hmac.compare_digest(client["token_hash"], hashlib.sha256(token.encode()).hexdigest())):
            raise ManagementError("view_client_denied", "Graph client capability is invalid.")
        return client

    def register(self):
        identity, token, stamp = uuid4().hex, uuid4().hex + uuid4().hex, now_iso()
        with self.document.locked():
            data = self._read()
            # Expired connection leases are runtime metadata, not user content.
            data["clients"] = {key: value for key, value in data["clients"].items() if _age(value["last_seen"]) <= 600}
            if len(data["clients"]) >= 32:
                raise ManagementError("view_client_limit", "Too many graph clients.")
            data["clients"][identity] = {"client_id": identity, "token_hash": hashlib.sha256(token.encode()).hexdigest(),
                                         "connected_at": stamp, "last_seen": stamp}
            self.document.write(data)
        return {"client_id": identity, "client_token": token, "lease_seconds": CLIENT_LEASE}

    def heartbeat(self, client_id, token):
        with self.document.locked():
            data = self._read();client = self._authenticate(data, client_id, token)
            client["last_seen"] = now_iso();self.document.write(data)
            return self._public_client(client)

    @staticmethod
    def _result(data, request, *, duplicate=False):
        acknowledgement = request.get("acknowledgement")
        target = data["clients"].get(request.get("client_id"))
        if acknowledgement:
            status = acknowledgement["status"]
        elif _age(request["requested_at"]) > INTENT_TTL:
            status = "expired"
        elif _age(request["requested_at"]) < 0:
            status = "waiting_clock"
        else:
            status = "queued" if target and 0 <= _age(target["last_seen"]) <= CLIENT_LEASE else "waiting"
        return {"operation_id": request["operation_id"], "view_id": request["view_id"],
                "view_revision": request["view_revision"], "client_id": request.get("client_id"),
                "requested_at": request["requested_at"], "status": status,
                "acknowledgement": deepcopy(acknowledgement), "duplicate": duplicate}

    def apply(self, arguments):
        args, digest = _request(arguments)
        with self.document.locked():
            data = self._read();old = data["requests"].get(args["operation_id"])
            if old:
                if old["digest"] != digest:
                    raise ManagementError("operation_conflict", "View apply operation has another payload.")
                return self._result(data, old, duplicate=True)
            view = self.views.get(args["id"])
            if view["revision"] != args["expected_revision"]:
                raise ManagementError("revision_conflict", "Saved view has changed.", actual_revision=view["revision"])
            if len(data["requests"]) >= 1000:
                raise ManagementError("view_delivery_limit", "View delivery receipt budget was reached.")
            target = args.get("client_id")
            if target and target not in data["clients"]:
                raise ManagementError("view_client_not_found", "Target graph client was not found.")
            if target is None:
                active = [key for key, value in data["clients"].items() if 0 <= _age(value["last_seen"]) <= CLIENT_LEASE]
                if len(active) > 1:
                    raise ManagementError("client_required", "Choose an exact graph client.", client_ids=active)
                target = active[0] if active else None
            request = {"operation_id": args["operation_id"], "digest": digest, "view_id": view["id"],
                       "view_revision": view["revision"], "client_id": target, "requested_at": now_iso()}
            data["requests"][args["operation_id"]] = request;self.document.write(data)
            return self._result(data, request)

    def apply_status(self, operation_id):
        _identity(operation_id);data = self._read();request = data["requests"].get(operation_id)
        return {"operation_id": operation_id, "found": request is not None,
                "result": self._result(data, request) if request else None}

    def verify_recorded_request(self, arguments):
        args, digest = _request(arguments);data = self._read();request = data["requests"].get(args["operation_id"])
        if request and request["digest"] != digest:
            raise ManagementError("operation_conflict", "View apply operation has another payload.")
        return {"found": request is not None, "result": self._result(data, request, duplicate=True) if request else None}

    def pending(self, client_id, token):
        data = self._read();self._authenticate(data, client_id, token)
        requests = [request for request in data["requests"].values() if
                    request.get("client_id") in {None, client_id} and not request.get("acknowledgement")
                    and 0 <= _age(request["requested_at"]) <= INTENT_TTL]
        requests.sort(key=lambda request: (request["requested_at"], request["operation_id"]))
        return {"requests": [self._result(data, request) for request in requests[:1]]}

    def claim(self, client_id, token, operation_id):
        _identity(operation_id)
        with self.document.locked():
            data = self._read();self._authenticate(data, client_id, token)
            request = data["requests"].get(operation_id)
            if not request or not 0 <= _age(request["requested_at"]) <= INTENT_TTL:
                raise ManagementError("view_delivery_expired", "View apply request is not pending.")
            if request.get("client_id") not in {None, client_id}:
                raise ManagementError("view_client_conflict", "Another graph client owns this delivery.")
            if request.get("client_id") is None:
                request["client_id"] = client_id;self.document.write(data)
            return self._result(data, request)

    def acknowledge(self, client_id, token, operation_id, status, observed_state=None, error_code=None):
        if status not in {"applied", "failed", "revision_conflict"}:
            raise ManagementError("validation_error", "Invalid graph acknowledgement status.")
        _identity(operation_id)
        if error_code is not None:
            _identity(error_code)
        acknowledgement_hash = hashlib.sha256(json.dumps({"status": status, "observed_state": observed_state,
                                                          "error_code": error_code}, sort_keys=True,
                                                         allow_nan=False).encode()).hexdigest()
        with self.document.locked():
            data = self._read();self._authenticate(data, client_id, token)
            request = data["requests"].get(operation_id)
            if not request or request.get("client_id") != client_id:
                raise ManagementError("view_client_conflict", "Graph acknowledgement has another target.")
            if request.get("acknowledgement"):
                if request["acknowledgement"].get("request_hash") != acknowledgement_hash:
                    raise ManagementError("operation_conflict", "Graph acknowledgement has a different payload.")
                return self._result(data, request, duplicate=True)
            if not 0 <= _age(request["requested_at"]) <= INTENT_TTL:
                raise ManagementError("view_delivery_expired", "View apply request has expired.")
            observation = None
            if status == "applied":
                view = self.views.get(request["view_id"])
                if view["revision"] != request["view_revision"]:
                    status, error_code = "revision_conflict", "revision_conflict"
                else:
                    observation = observe(view["state"], observed_state)
                    if not observation["matched"]:
                        status, error_code = "failed", "view_observation_mismatch"
            request["acknowledgement"] = {"status": status, "client_id": client_id, "observed_at": now_iso(),
                                           "error_code": error_code, "observation": observation,
                                           "request_hash": acknowledgement_hash}
            self.document.write(data)
            return self._result(data, request)
