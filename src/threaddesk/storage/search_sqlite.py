"""Disposable FTS projection. Canonical writes never depend on index success."""
from __future__ import annotations

import json
import sqlite3
from time import monotonic
from uuid import uuid4

from threaddesk.core.search import CALL_BYTES, CANDIDATES, RECORD_BYTES, SearchError
from threaddesk.storage.schema import FTS_SQL
from threaddesk.storage.search_source import document, identifier, projection_digest

KINDS = ("thread:title", "thread:description", "thread:notes")
META = """CREATE TABLE IF NOT EXISTS thread_search_meta(
 id TEXT PRIMARY KEY, revision INTEGER, digest TEXT, project_id TEXT, status TEXT,
 title_rowid INTEGER, description_rowid INTEGER, notes_rowid INTEGER)"""


class SQLiteSearchAdapter:
    managed_generation = True

    def __init__(self, store):
        self.store = store
        self.root = store.workspace_path
        self._read_connection = None

    def _reader(self):
        if self._read_connection is None:
            self._read_connection = sqlite3.connect(
                self.store.database_path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.1)
        return self._read_connection

    def close(self):
        if self._read_connection is not None:
            self._read_connection.close()
            self._read_connection = None

    def _config(self):
        db = self.store.connection if self.store._transaction_depth else self._reader()
        row = db.execute(
            "SELECT CASE WHEN length(CAST(value AS BLOB))<=16384 THEN value END "
            "FROM app_state WHERE key='local_search'").fetchone()
        if row is None:
            return {"enabled": False, "status": "disabled", "epoch": "", "incarnation": ""}
        data = json.loads(row[0])
        if (type(data.get("format")) is not int or data["format"] != 1 or type(data.get("enabled")) is not bool
                or any(not isinstance(data.get(key), str) or len(data[key]) > 128
                       for key in ("epoch", "incarnation", "status"))):
            raise ValueError("invalid search state")
        return data

    def _put(self, config):
        self.store.connection.execute(
            "INSERT OR REPLACE INTO app_state(key,value) VALUES('local_search',?)",
            (json.dumps(config),))

    def _marker_matches(self, config, db=None):
        row = (db or self.store.connection).execute(
            "SELECT entity_type,entity_id FROM search_index WHERE rowid=?",
            (config.get("control_rowid", -1),)).fetchone()
        return row is not None and tuple(row) == ("search_control", config.get("indexed_epoch"))

    def state(self):
        if self.store._transaction_depth:
            return {"enabled": False, "status": "unavailable", "generation": "",
                    "reason": "write_transaction_active"}
        try:
            config = self._config()
            # Local observer on this persistent read-only connection. Canonical
            # commits happen on another connection, including when optional
            # epoch writes fail. This is not a persisted/global snapshot token.
            version = self._reader().execute("PRAGMA data_version").fetchone()[0]
            generation = config["incarnation"] + ":" + config["epoch"] + ":" + str(version)
        except Exception:
            return {"enabled": False, "status": "unavailable", "generation": "",
                    "reason": "search_state_invalid"}
        try:
            mode = "fts5" if config["status"] == "ready" and config["epoch"] == config.get("indexed_epoch") else "bounded_scan"
            if mode == "fts5":
                if not self._marker_matches(config, self._reader()):
                    raise ValueError("missing derived publication marker")
                self._reader().execute("SELECT id FROM thread_search_meta LIMIT 1").fetchone()
            return {**config, "mode": mode,
                    "generation": generation}
        except Exception:
            return {**config, "status": "degraded", "mode": "bounded_scan",
                    "generation": generation,
                    "reason": "search_index_invalid"}

    def configure(self, enabled):
        with self.store.transaction():
            config = {"format": 1, "enabled": enabled, "status": "needs_rebuild" if enabled else "disabled",
                      "epoch": uuid4().hex, "incarnation": uuid4().hex}
            if enabled:
                self.store.connection.execute(META)
                try:
                    self.store.connection.execute(FTS_SQL)
                except sqlite3.Error:
                    config["status"] = "no_fts5"
            self._put(config)
        return self.state()

    def read(self, exact_id, *, canonical=False):
        identifier(exact_id)
        if self.store.object_in_trash("thread", exact_id):
            raise SearchError("source_in_trash")
        # Check length before materializing an untrusted source payload.
        db = self.store.connection if canonical else self._reader()
        row = db.execute(
            "SELECT CASE WHEN length(CAST(payload AS BLOB))<=? THEN payload END,"
            "length(CAST(payload AS BLOB)) FROM threads WHERE id=?", (RECORD_BYTES, exact_id)).fetchone()
        if row is None or row[0] is None:
            raise SearchError("source_unreadable_or_over_limit")
        data = json.loads(row[0])
        doc = document(data, row[1])
        if doc.thread_id != exact_id:
            raise SearchError("source_identity_mismatch")
        return doc

    def candidates(self, terms, project_id, include_archived, *, indexed=False):
        after = 0
        while True:
            # An owned read connection keeps progress handlers and long-lived
            # query cursors off the canonical connection and its transactions.
            db = self._reader()
            paused = None
            try:
                end = monotonic() + 0.1
                db.set_progress_handler(lambda: int(monotonic() > end), 1000)
                if indexed:
                    expression = " AND ".join('"' + term.replace('"', '""') + '"' for term in terms)
                    sql = """SELECT search_index.rowid,substr(entity_id,1,129),entity_type FROM search_index
                      JOIN thread_search_meta m ON m.id=entity_id
                      WHERE search_index MATCH ? AND search_index.rowid>?
                      AND entity_type IN ('thread:title','thread:description','thread:notes')"""
                    params = [expression, after]
                    if project_id is not None:
                        sql += " AND m.project_id=?"
                        params.append(project_id)
                    if not include_archived:
                        sql += " AND m.status!='archived'"
                    rows = db.execute(sql + " ORDER BY search_index.rowid LIMIT ?", (*params, CANDIDATES)).fetchall()
                else:
                    rows = db.execute("SELECT rowid,substr(id,1,129) FROM threads WHERE rowid>? ORDER BY rowid LIMIT ?",
                                      (after, CANDIDATES)).fetchall()
            except sqlite3.OperationalError as exc:
                code = getattr(exc, "sqlite_errorcode", None)
                if code == 9 or str(exc) == "interrupted":
                    paused = "time_budget"
                elif code in (5, 6) or str(exc) == "database is locked":
                    paused = "source_busy"
                else:
                    raise
            finally:
                db.set_progress_handler(None, 0)
            if paused:
                # Keep the same keyset position alive. Interruption/busy is a
                # partial query, not evidence that source/index changed.
                yield None, paused
                continue
            if not rows:
                return
            for row in rows:
                after = row[0]
                yield (row[1], row[2].split(":", 1)[1]) if indexed else (row[1], None)

    def _replace(self, exact_id, doc=None):
        db = self.store.connection
        previous = db.execute(
            "SELECT title_rowid,description_rowid,notes_rowid FROM thread_search_meta WHERE id=?", (exact_id,)).fetchone()
        if previous is not None:
            # entity_id is UNINDEXED in FTS5: deleting by it would scan the
            # complete projection for every insert/update (quadratic rebuild).
            db.executemany("DELETE FROM search_index WHERE rowid=?", [(rowid,) for rowid in previous])
        db.execute("DELETE FROM thread_search_meta WHERE id=?", (exact_id,))
        if doc is not None:
            rowids = []
            for name in ("title", "description", "notes"):
                cursor = db.execute("INSERT INTO search_index(entity_type,entity_id,title,body,visibility) VALUES(?,?,?,?,?)",
                                    ("thread:" + name, exact_id, "", getattr(doc, name), "local_file_owner"))
                rowids.append(cursor.lastrowid)
            db.execute("INSERT INTO thread_search_meta VALUES(?,?,?,?,?,?,?,?)", (
                exact_id, doc.revision, projection_digest(doc), doc.project_id, doc.status, *rowids))

    def changed(self, exact_id, *, deleted=False):
        """Called inside the existing canonical write transaction only."""
        try:
            config = self._config()
            if not config["enabled"]:
                return
            was_ready = config["status"] == "ready" and config["epoch"] == config.get("indexed_epoch")
            if was_ready:
                try:
                    was_ready = self._marker_matches(config)
                except sqlite3.Error:
                    was_ready = False
                if not was_ready:
                    config["status"] = "stale"
            config["epoch"] = uuid4().hex
            if was_ready:
                config["status"] = "stale"
            try:
                # Persist independent dirty state before any FTS mutation. A
                # denied marker DELETE must not leave the old epoch published.
                self._put(config)
            except Exception:
                if not self.store.connection.in_transaction:
                    raise
                if was_ready:
                    # An isolated optional-state write failure still has the
                    # independent marker as a way to revoke publication.
                    self.store.connection.execute("DELETE FROM search_index WHERE rowid=?",
                                                  (config["control_rowid"],))
                raise
            if was_ready:
                self.store.connection.execute("DELETE FROM search_index WHERE rowid=?",
                                              (config["control_rowid"],))
            self.store.connection.execute("SAVEPOINT optional_search")
            try:
                self._replace(exact_id, None if deleted else self.read(exact_id, canonical=True))
                if was_ready:
                    marker = self.store.connection.execute(
                        "INSERT INTO search_index(entity_type,entity_id,title,body,visibility) VALUES('search_control',?,'','','local_file_owner')",
                        (config["epoch"],))
                    config["control_rowid"] = marker.lastrowid
                    config["indexed_epoch"] = config["epoch"]
                    config["status"] = "ready"
                self.store.connection.execute("RELEASE optional_search")
            except Exception:
                if not self.store.connection.in_transaction:
                    # SQLITE_FULL/IOERR/RAISE(ROLLBACK) can abort the entire
                    # canonical transaction. Never turn that into save success.
                    raise
                try:
                    self.store.connection.execute("ROLLBACK TO optional_search")
                    self.store.connection.execute("RELEASE optional_search")
                except sqlite3.Error as exc:
                    raise RuntimeError("optional_search_savepoint_lost") from exc
                config["status"] = "stale"
            self._put(config)
        except (sqlite3.Error, ValueError, KeyError, TypeError, AttributeError):
            if not self.store.connection.in_transaction:
                raise
            # Disposable state must never reject an otherwise valid save.
            return

    def rebuild(self):
        config = self._config()
        if not config["enabled"]:
            raise SearchError("search_disabled")
        try:
            with self.store.transaction():
                self.store.connection.execute(META)
                self.store.connection.execute(FTS_SQL)
                if config["status"] not in {"cleaning", "building"}:
                    config.update(status="cleaning", incarnation=uuid4().hex,
                                  build_epoch=config["epoch"], after=0, skipped=0)
                if config["status"] == "cleaning":
                    rows = self.store.connection.execute(
                        "SELECT rowid FROM search_index WHERE entity_type IN (?,?,?,?) LIMIT ?",
                        (*KINDS, "search_control", CANDIDATES)).fetchall()
                    self.store.connection.executemany("DELETE FROM search_index WHERE rowid=?", [(r[0],) for r in rows])
                    metadata = self.store.connection.execute("SELECT id FROM thread_search_meta LIMIT ?", (CANDIDATES,)).fetchall()
                    self.store.connection.executemany("DELETE FROM thread_search_meta WHERE id=?", metadata)
                    if not rows and not metadata:
                        config["status"] = "building"
                else:
                    count, size = 0, 0
                    rows = self.store.connection.execute(
                        "SELECT rowid,substr(id,1,129),length(CAST(payload AS BLOB)) FROM threads WHERE rowid>? ORDER BY rowid LIMIT ?",
                        (config["after"], CANDIDATES)).fetchall()
                    for rowid, exact_id, length in rows:
                        if size + min(length, RECORD_BYTES) > CALL_BYTES:
                            break
                        size += min(length, RECORD_BYTES)
                        try:
                            doc = self.read(exact_id, canonical=True)
                            self._replace(exact_id, doc)
                        except Exception:
                            config["skipped"] += 1
                        config["after"] = rowid
                        count += 1
                    if not rows:
                        config["status"] = "ready" if config["epoch"] == config["build_epoch"] and not config["skipped"] else "partial"
                        config["indexed_epoch"] = config["build_epoch"]
                        if config["status"] == "ready":
                            marker = self.store.connection.execute(
                                "INSERT INTO search_index(entity_type,entity_id,title,body,visibility) VALUES('search_control',?,'','','local_file_owner')",
                                (config["epoch"],))
                            config["control_rowid"] = marker.lastrowid
                    config.update(last_batch_records=count, last_batch_bytes=size)
                self._put(config)
        except sqlite3.Error:
            with self.store.transaction():
                config["status"] = "no_fts5_or_corrupt"
                self._put(config)
        return self.state()
