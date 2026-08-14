# ThreadDesk

Lokale Control-Layer vor Gnom-Hub. Speichert Threads und Kontext. Führt nichts aus.

**MVP v0.1:** Threads · persistenter Kontext · Switcher · Snapshots.

## Install

```bash
cd threaddesk
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

Daten liegen unter `~/.threaddesk/` (JSON, lokal).

## CLI

```bash
td new "Gnom-Hub Switcher"
td list
td switch <id-or-prefix>
td current
td note "Wir bleiben beim strikten MVP."
td snap save "vor-umbau"
td snap list
td snap load <snap-id>
td rename <id> "Neuer Titel"
td archive <id>
td delete <id>          # nur archivierte
```

Wechsel stellt den vollen Kontext wieder her. Kein Agent wird gestartet.

## Was bewusst fehlt (Phase 4+)

Kanban, Prompt-Generator, MCP, Grok-Build-Bridge, Tollgate, Dashboard.

## Prinzip

Brainstorm freely — Execute only when pressed. ThreadDesk bereitet vor. Gnom-Hub führt aus.
