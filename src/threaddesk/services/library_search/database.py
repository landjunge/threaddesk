"""Disposable SQLite FTS projection. Canonical files remain the source of truth."""

from __future__ import annotations

import json
import sqlite3
import stat
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote

COLUMNS = "entity_type,record_id,thread_id,node_id,project_id,format,assignment,updated_at,trashed"


class SearchDatabase:
    def __init__(self, root):
        self.root = Path(root)
        self.path = self.root / "content-search.sqlite3"

    def _guard(self):
        if (
            self.root.is_symlink()
            or self.path.is_symlink()
            or any(
                self.path.with_name(self.path.name + suffix).is_symlink()
                for suffix in ("-journal", "-wal", "-shm")
            )
        ):
            raise OSError("index_unsafe_path")
        if self.path.exists():
            info = self.path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise OSError("index_unsafe_path")

    @contextmanager
    def connect(self, *, write=False):
        self._guard()
        if write:
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            db = sqlite3.connect(str(self.path), timeout=2)
            self.path.chmod(0o600)
            db.execute("BEGIN IMMEDIATE")
        else:
            db = sqlite3.connect(
                "file:" + quote(str(self.path.resolve())) + "?mode=ro",
                uri=True,
                timeout=1,
            )
        db.row_factory = sqlite3.Row
        try:
            yield db
            if write:
                db.commit()
        except Exception:
            if write:
                db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def initialize(db):
        db.execute(
            "CREATE TABLE IF NOT EXISTS documents(key TEXT PRIMARY KEY, entity_type TEXT, record_id TEXT, thread_id TEXT, node_id TEXT, project_id TEXT, format TEXT, assignment TEXT, updated_at TEXT, trashed INTEGER, payload TEXT, normalized TEXT, fingerprint TEXT)"
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS documents_scope ON documents(entity_type,thread_id,project_id,trashed)"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT)"
        )
        mode = db.execute("SELECT value FROM metadata WHERE key='mode'").fetchone()
        if mode:
            return mode[0]
        try:
            db.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(key UNINDEXED, normalized, tokenize='trigram')"
            )
            mode = "fts5_trigram"
        except sqlite3.OperationalError:
            try:
                db.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(key UNINDEXED, normalized, tokenize='unicode61 remove_diacritics 2')"
                )
                mode = "fts5_tokens"
            except sqlite3.OperationalError:
                mode = "bounded_scan"
        db.execute("INSERT INTO metadata VALUES('mode',?)", (mode,))
        return mode

    @staticmethod
    def replace(db, documents, entity_types):
        previous = {
            row[0]
            for row in db.execute(
                "SELECT key FROM documents WHERE entity_type IN ({})".format(
                    ",".join("?" for _ in entity_types)
                ),
                entity_types,
            )
        }
        seen = set()
        for doc in documents:
            key = doc["key"]
            seen.add(key)
            old = db.execute(
                "SELECT fingerprint FROM documents WHERE key=?", (key,)
            ).fetchone()
            if old and old[0] == doc["fingerprint"]:
                continue
            values = [doc.get(name) for name in COLUMNS.split(",")]
            payload = {
                name: value
                for name, value in doc.items()
                if name not in {"normalized", "fingerprint"}
            }
            db.execute(
                "INSERT OR REPLACE INTO documents VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    key,
                    *values,
                    json.dumps(payload, ensure_ascii=False),
                    doc["normalized"],
                    doc["fingerprint"],
                ],
            )
            mode = db.execute("SELECT value FROM metadata WHERE key='mode'").fetchone()[
                0
            ]
            if mode != "bounded_scan":
                db.execute("DELETE FROM documents_fts WHERE key=?", (key,))
                db.execute(
                    "INSERT INTO documents_fts VALUES(?,?)", (key, doc["normalized"])
                )
        for key in previous - seen:
            db.execute("DELETE FROM documents WHERE key=?", (key,))
            mode = db.execute("SELECT value FROM metadata WHERE key='mode'").fetchone()[
                0
            ]
            if mode != "bounded_scan":
                db.execute("DELETE FROM documents_fts WHERE key=?", (key,))

    def query(self, query_terms, filters, limit, offset):
        with self.connect() as db:
            mode = db.execute("SELECT value FROM metadata WHERE key='mode'").fetchone()[
                0
            ]
            clauses, params = [], []
            # Trigrams implement literal infix search. Older SQLite keeps the
            # same semantics with an explicit bounded SQL fallback.
            if (
                mode == "fts5_trigram"
                and query_terms
                and all(len(term) >= 3 for term in query_terms)
            ):
                clauses.append(
                    "d.key IN (SELECT key FROM documents_fts WHERE documents_fts MATCH ?)"
                )
                params.append(
                    " AND ".join(
                        '"' + term.replace('"', '""') + '"' for term in query_terms
                    )
                )
            else:
                for term in query_terms:
                    clauses.append("instr(d.normalized,?)>0")
                    params.append(term)
            for column, value in filters.items():
                if column == "include_trashed":
                    if not value:
                        clauses.append("d.trashed=0")
                elif column == "date_from":
                    clauses.append("d.updated_at>=?")
                    params.append(value)
                elif column == "date_to":
                    clauses.append("substr(d.updated_at,1,10)<=?")
                    params.append(value[:10])
                elif column == "kind":
                    clauses.append(
                        "(d.format=? OR json_extract(d.payload,'$.family')=? OR json_extract(d.payload,'$.suffix')=?)"
                    )
                    params.extend(
                        [value, value, value if value.startswith(".") else "." + value]
                    )
                elif column in COLUMNS.split(","):
                    clauses.append("d." + column + "=?")
                    params.append(value)
            sql = "SELECT payload FROM documents d WHERE " + (
                " AND ".join(clauses) or "1"
            )
            # A progress budget makes malformed/very broad queries bounded on
            # older Intel hardware rather than monopolising a request worker.
            from time import monotonic

            deadline = monotonic() + 0.5
            db.set_progress_handler(lambda: int(monotonic() > deadline), 1000)
            rows = db.execute(
                sql + " ORDER BY d.entity_type,d.key LIMIT ? OFFSET ?",
                [*params, limit, offset],
            ).fetchall()
            return [json.loads(row[0]) for row in rows]
