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
td list                 # Nummer + ID + Status
td switch 1             # Nummer, ID, Prefix oder Titel
td current              # voller Kontext
td note "Stand heute"
td note -a "nächster Schritt"
td status active        # idea | active | paused | done
td files add ~/threaddesk/PLAN.md
td snap save "vor-umbau"
td snap list
td snap load <snap-id>
td archive 1
td delete 1 --yes       # nur archivierte
td prompt                    # aus aktuellem Thread, Ziel grok
td prompt --target gnom --variant short
td prompt --save              # im Thread ablegen, nicht ausführen
td prompt --list
td handoff                    # ~/.threaddesk/handoff.json für Gnom-Hub
td mcp                        # MCP-Server auf stdin/stdout
```

Wechsel stellt den vollen Kontext wieder her. Kein Agent wird gestartet.

Prompt-Generator ist lokal (Vorlage, kein API-Call). Er bereitet Text vor. Es wird niemand angerufen.

MCP stellt nur Thread-Daten bereit. Kein `delete`, keine Agent-Starts. Notizen kommen als `<untrusted>`. Siehe `docs/MCP.md`.

## Später (noch nicht)

Grok-Build-Bridge, Tollgate, Kanban-Dashboard.

## Prinzip

Brainstorm freely — Execute only when pressed. ThreadDesk bereitet vor. Gnom-Hub führt aus.
