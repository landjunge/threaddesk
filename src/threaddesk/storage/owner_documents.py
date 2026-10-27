"""Explicit migration of the two owner documents without a mixed file/SQL commit.

SQLite keeps the initial migrated value in app_state. The owning service reads
it only while no newer owner file exists. This is a migration source, not a
second runtime graph/activity implementation.
"""
from __future__ import annotations

import json

NAMES = ("file-activity.json", "graph-views.json")
KEY = "migrated_graph_owner_documents_v1"
LIMIT = 16 * 1024 * 1024


def read_owner_documents(store):
    from threaddesk.storage.workspace_backup import _SourceTree

    values = {}
    with _SourceTree(store.workspace_path) as source:
        for name in NAMES:
            try:
                expected = source.info(name)
            except Exception as exc:
                cause = exc
                missing = False
                while cause is not None:
                    missing |= isinstance(cause, FileNotFoundError)
                    cause = cause.__cause__
                if not missing:
                    raise
                fallback = getattr(store, "get_migrated_owner_document", lambda _: None)(name)
                if fallback is not None:
                    values[name] = fallback
                continue
            data = json.loads(source.read(name, expected, limit=LIMIT))
            if not isinstance(data, dict) or data.get("schema_version") != 1:
                raise ValueError("Invalid graph owner document")
            values[name] = data
    return values


class MigratedOwnerDocuments:
    def save_migrated_owner_documents(self, documents):
        if set(documents) - set(NAMES):
            raise ValueError("Unknown owner document")
        encoded = json.dumps(documents, sort_keys=True, ensure_ascii=False, allow_nan=False)
        if len(encoded.encode()) > LIMIT * len(NAMES):
            raise ValueError("Owner document migration exceeds budget")
        self.connection.execute("INSERT OR REPLACE INTO app_state(key,value) VALUES(?,?)", (KEY, encoded))
        self._commit()

    def get_migrated_owner_document(self, name):
        if name not in NAMES:
            raise ValueError("Unknown owner document")
        row = self.connection.execute("SELECT value FROM app_state WHERE key=?", (KEY,)).fetchone()
        if row is None:
            return None
        return json.loads(row["value"]).get(name)
