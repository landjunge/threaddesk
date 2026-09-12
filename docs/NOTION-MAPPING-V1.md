# ThreadDesk Notion mapping v1

This document fixes the deterministic mapping and diff rules used after a
`threaddesk-notion-bundle-v1` has passed validation. Machine values stay in
English; the later user interface translates labels and reasons to DE or EN.

The mapper creates proposals only. It never writes a node, relation, source
record or file and it never turns an exporter suggestion into a confirmed
fact.

## Objects

- A `suggested_kind` that is an existing ThreadDesk node kind becomes a mapped
  draft with rule `notion.v1.suggested_kind`.
- An unknown kind becomes a `document` with status `unverified` and mapping
  state `open`. The original kind, mapping reason, properties and Markdown are
  preserved.
- An archived source becomes an archive proposal. It is not silently deleted.
- Known source status values are preserved for known kinds. Unknown values use
  the safe ThreadDesk default for the kind.
- Target IDs are deterministic from source workspace and source ID.
- Original Markdown is copied into the draft unchanged. Mapping does not
  translate, repair or execute it.

## Relations

Known ThreadDesk relation kinds remain unchanged. Unknown relation kinds are
represented as `related_to` drafts with mapping state `open`; the original
kind remains in metadata. Open relations are not eligible for an automatic
commit.

## Provenance and source records

Each draft carries source system, stable source ID, URL, path, type, source
edit time, content hash, bundle ID and mapping rule. A reviewed import later
stores a `SourceRecord` with the source hash and the logical target hash. The
record key is `(source_system, source_id)`.

Schema version 2 adds `source_records` to SQLite. Opening an existing schema
version 1 workspace performs the idempotent local migration. The JSON adapter
retains the same record contract so a later JSON-to-SQLite move is lossless.

## Diff rules

1. Same source ID and same source hash: `noop`, even if local work continued.
2. Changed source and unchanged recorded target: `update` proposal.
3. Changed source and locally changed or missing target: `conflict`.
4. New source with a strongly similar local title: `possible_duplicate`.
5. New source without a candidate: `new`.
6. Unknown mapping: `open`.
7. Explicitly archived source with an unchanged target: `archive` proposal.
8. Missing source in a later bundle creates no delete or archive proposal.
9. Exclusions stay visible with source ID, title and reason only.

The result is immutable at its public boundary and contains structured counts.
It is a dry-run: no store method is required and no product data changes.
