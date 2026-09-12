"""Versioned SQLite schema for ThreadDesk's local workspace."""

SCHEMA_VERSION = 1

TABLES = ("threads", "snapshots", "nodes", "relations", "graph_events")

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS schema_info (
    version INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS app_state (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS threads (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_threads_status_updated
    ON threads(status, updated_at DESC, id DESC);
CREATE TABLE IF NOT EXISTS snapshots (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL,
    FOREIGN KEY(thread_id) REFERENCES threads(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_snapshots_thread_created
    ON snapshots(thread_id, created_at DESC);
CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_nodes_kind_status_updated
    ON nodes(kind, status, updated_at DESC, id DESC);
CREATE TABLE IF NOT EXISTS relations (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL,
    FOREIGN KEY(source_id) REFERENCES nodes(id),
    FOREIGN KEY(target_id) REFERENCES nodes(id)
);
CREATE INDEX IF NOT EXISTS idx_relations_source ON relations(source_id, kind);
CREATE INDEX IF NOT EXISTS idx_relations_target ON relations(target_id, kind);
CREATE TABLE IF NOT EXISTS graph_events (
    id TEXT PRIMARY KEY,
    occurred_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_graph_events_occurred
    ON graph_events(occurred_at, id);
CREATE TABLE IF NOT EXISTS import_batches (
    id TEXT PRIMARY KEY,
    payload TEXT NOT NULL
);
"""

FTS_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(
    entity_type UNINDEXED,
    entity_id UNINDEXED,
    title,
    body,
    visibility UNINDEXED
);
"""
