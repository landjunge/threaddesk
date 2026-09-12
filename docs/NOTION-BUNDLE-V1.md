# ThreadDesk Notion bundle v1

This is the machine contract for a local `.tdbundle`. It is deliberately
written in English because field names and error codes must stay stable across
the German and English user interfaces.

ThreadDesk does not connect to Notion. An explicitly tasked external tool may
read selected Notion roots and create this file. ThreadDesk only validates the
local file. Dropping or selecting a bundle never starts an import.

## Container

`threaddesk-notion-bundle-v1` is a ZIP file with the extension `.tdbundle`.
All text is UTF-8. Timestamps are ISO 8601 and include a UTC offset.

```text
manifest.json
objects.ndjson
relations.ndjson
exclusions.json
report.md
content/<source-id>.md
attachments/<safe-name>.<allowed-extension>
```

The archive may contain only these root files and files below `content/` or
`attachments/`. Paths are POSIX relative paths. Absolute paths, backslashes,
drive prefixes, `.` and `..` segments, symlinks, encrypted entries, nested
archives and executable/script content are rejected.

## Manifest

```json
{
  "format": "threaddesk-notion-bundle-v1",
  "schema_version": 1,
  "export_id": "export-2026-09-12-001",
  "created_at": "2026-09-12T20:00:00+00:00",
  "source_workspace_id": "workspace-redacted",
  "roots": ["root-page-id"],
  "counts": {
    "objects": 1,
    "relations": 0,
    "content": 1,
    "attachments": 0,
    "exclusions": 1
  },
  "files": {
    "objects.ndjson": {"sha256": "<64 lowercase hex>", "size": 640},
    "relations.ndjson": {"sha256": "<64 lowercase hex>", "size": 0},
    "exclusions.json": {"sha256": "<64 lowercase hex>", "size": 92},
    "report.md": {"sha256": "<64 lowercase hex>", "size": 120},
    "content/root-page-id.md": {"sha256": "<64 lowercase hex>", "size": 400}
  }
}
```

Every non-directory member except `manifest.json` must appear exactly once in
`files`. No listed file may be missing and no unlisted file may be present.
The declared size and SHA-256 must match the stored member.

## Object record

`objects.ndjson` contains one JSON object per non-empty line:

```json
{
  "source_id": "root-page-id",
  "title": "ThreadDesk",
  "source_path": "NetzwerkPunkt/ThreadDesk",
  "source_url": "https://www.notion.so/root-page-id",
  "source_type": "page",
  "parent_id": null,
  "last_edited_at": "2026-09-12T19:30:00+00:00",
  "properties": {"status": "active"},
  "content_path": "content/root-page-id.md",
  "content_sha256": "<sha256 of the Markdown member>",
  "archived": false,
  "suggested_kind": "project",
  "mapping_reason": "Active product page"
}
```

`source_id` is unique inside the bundle. `content_path` and
`content_sha256` are either both `null` or both valid. Every content file must
be referenced by an object. The suggested kind and reason are proposals; they
do not become confirmed ThreadDesk facts during validation.

## Relation record

`relations.ndjson` contains:

```json
{"source_id":"root-page-id","target_id":"decision-page-id","kind":"contains"}
```

Both IDs must resolve to object records in the same bundle. Mapping relation
kinds to ThreadDesk belongs to TD-NM6, not to this validator.

## Exclusions

`exclusions.json` is an array. It records only enough to prove that an item was
deliberately omitted:

```json
[
  {"source_id": "private-page-id", "title": "Private", "reason": "private"}
]
```

It must not contain the excluded secret or private document body. An excluded
ID must not also occur in `objects.ndjson`.

## Validation result

Validation is read-only and returns the bundle SHA-256, immutable manifest and
counts, plus streaming object and relation iterators. It does not create graph
objects, copy the bundle, call a URL or mutate the workspace.

Error codes are stable machine values such as `checksum`, `path`, `secret`,
`relation_target` and `compression_ratio`. The later UI translates them to DE
or EN. A secret failure names only the file or record location and never echoes
the detected value.

## Limits

Default limits are 10,000 files, 100 MiB per file, 1 GiB total uncompressed,
a maximum compression ratio of 100:1 and 2 MiB per NDJSON line. They can be
lowered for tests or constrained environments. Raising them is an explicit
local configuration decision, not information supplied by the bundle.

## Versioning

Unknown `format` or required `schema_version` values fail closed. Optional
future fields may be preserved, but the meaning of v1 fields is never changed
in place. A breaking change receives a new format/version and its own tests.

Machine-readable record schemas are versioned in `docs/schemas/`:

- `notion-manifest-v1.schema.json`
- `notion-object-v1.schema.json`
- `notion-relation-v1.schema.json`
- `notion-exclusions-v1.schema.json`

The runtime performs the same checks without adding a JSON-Schema library to
the application. The schemas exist for external bundle producers and reviews.
