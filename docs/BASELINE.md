# ThreadDesk baseline (TD-NM0)

This report freezes the observable baseline before storage and service modules are split. The characterization tests are the executable source of truth; this document records how the baseline was reproduced.

## Reference environment

- Main commit: `3193d096b747cb5caa7783e5c741ce3c31d40bf3`
- Captured: 2026-09-12
- Python: 3.12.14 (project supports Python 3.9 or newer)
- Package: ThreadDesk 0.1.0, editable installation
- Test baseline before TD-NM0: 161 passed, 19 skipped
- Test result with TD-NM0 protection: 169 passed, 19 skipped
- Declared development/UI/browser dependencies: pytest 9.1.1, httpx 0.28.1, FastAPI 0.141.1, Uvicorn 0.52.4, Jinja2 3.1.6, python-multipart 0.0.32, Playwright 1.62.0

## Reproduce

```sh
python -m venv .venv
.venv/bin/python -m pip install -e '.[dev,ui,browser]'
.venv/bin/python -m pytest -q
.venv/bin/td --help
```

For an isolated installation smoke test:

```sh
python -m build
python -m venv /tmp/threaddesk-install-smoke
/tmp/threaddesk-install-smoke/bin/python -m pip install dist/threaddesk-0.1.0-py3-none-any.whl
/tmp/threaddesk-install-smoke/bin/td --help
```

## Protected behavior

- `JsonStore` creates an empty workspace, loads the anonymized small fixture, applies safe defaults to the legacy fixture, and exposes malformed JSON as an error.
- `ThreadService` persists current-thread state, snapshots, graph nodes, relations and events across a fresh service instance.
- CLI command names, MCP tool names and the existing UI route surface are pinned.
- Tollgate checks do not consume quota; Gnom and Grok only write local packages and report `ran: false`.
- ThreadDesk has no Notion/import route, token, or network behavior at this baseline.

Fixtures live in `tests/fixtures/json_store/`: `empty`, `small`, `legacy`, and `corrupt`. They contain no personal data or credentials.

The isolated wheel build and install completed successfully. Setuptools emitted a non-blocking deprecation warning for the table form of `project.license`; changing package metadata is outside this behavior-preserving work package.
