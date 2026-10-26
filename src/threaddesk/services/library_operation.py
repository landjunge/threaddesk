"""Bind public operation IDs to one command; domain owners retain result receipts."""
import hashlib
import json

from threaddesk.core.errors import ManagementError
from threaddesk.core.models import now_iso

SAFE_REJECTIONS = frozenset({"validation_error", "not_found", "revision_conflict", "name_conflict",
                            "trash_generation_conflict", "object_in_trash", "external_open_blocked",
                            "no_default_application", "invalid_manifest", "source_missing",
                            "source_not_directory", "source_too_broad", "source_is_store"})


class LibraryOperationBinding:
    def __init__(self, store):
        self.store = store

    @staticmethod
    def key(identity):
        return "library-command-" + hashlib.sha256(identity.encode()).hexdigest()

    @staticmethod
    def fingerprint(arguments):
        canonical = dict(arguments)
        if canonical.get("action") not in {"open", "resume", "refresh_sources"}:
            canonical.setdefault("data", {})
        return hashlib.sha256(json.dumps(canonical, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

    def read(self, identity):
        return self.store.get_management_operation(self.key(identity))

    def bind(self, arguments):
        identity = arguments["operation_id"]
        fingerprint = self.fingerprint(arguments)
        with self.store.transaction():
            previous = self.read(identity)
            if previous:
                if arguments["action"] == "resume" and previous["action"] == "import":
                    return
                if previous["request_hash"] != fingerprint:
                    raise ManagementError("operation_conflict", "Operation ID belongs to a different library request.")
                return
            self.store.save_management_operation(self.key(identity), {
                "request_hash": fingerprint, "action": arguments["action"], "state": "bound",
                "recorded_at": now_iso(), "result": {"owner": "library", "status": "unknown", "action": arguments["action"]}})

    def rejected(self, arguments, error):
        if not isinstance(arguments, dict) or not isinstance(arguments.get("operation_id"), str):
            return
        if getattr(error, "code", None) not in SAFE_REJECTIONS:
            return
        identity = arguments["operation_id"]
        with self.store.transaction():
            previous = self.read(identity)
            if previous and previous["request_hash"] == self.fingerprint(arguments):
                # Keep this information in the existing owner table, never claim
                # a post-commit uncertain I/O error was a definite rejection.
                key = "library-rejection-" + hashlib.sha256(identity.encode()).hexdigest()
                if self.store.get_management_operation(key) is None:
                    self.store.save_management_operation(key, {"state": "rejected", "error": error.code, "request_hash": previous["request_hash"],
                                                                "recorded_at": now_iso(), "result": {"status": "failed", "code": error.code}})

    def rejection(self, identity):
        key = "library-rejection-" + hashlib.sha256(identity.encode()).hexdigest()
        return self.store.get_management_operation(key)

    def result(self, identity):
        key = "library-result-" + hashlib.sha256(identity.encode()).hexdigest()
        saved = self.store.get_management_operation(key)
        return saved["result"] if saved else None

    def completed(self, identity, result):
        key = "library-result-" + hashlib.sha256(identity.encode()).hexdigest()
        with self.store.transaction():
            previous = self.store.get_management_operation(key)
            if previous is None:
                self.store.save_management_operation(key, {"result": result,
                    "request_hash": self.read(identity)["request_hash"], "recorded_at": now_iso()})
        return self.result(identity)
