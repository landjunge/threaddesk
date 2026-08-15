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
td grok                       # Grok-Paket schreiben, Befehl zeigen, nicht starten
td grok --execute             # Execute-Paket, immer noch kein Start
td gate                       # Loop-/Tages-Schutz
td gate freeze                # Execute/Handoff sperren
td dash                       # Tafel im Terminal + ~/.threaddesk/dashboard.html
td dash --open                # HTML lokal öffnen
td gnom                       # Gnom-Paket (@bs) + curl, nichts senden
td gnom --execute --agent CoderAG
```

Wechsel stellt den vollen Kontext wieder her. Kein Agent wird gestartet.

Prompt-Generator ist lokal (Vorlage, kein API-Call). Er bereitet Text vor. Es wird niemand angerufen.

MCP stellt nur Thread-Daten bereit. Kein `delete`, keine Agent-Starts. Notizen kommen als `<untrusted>`. Siehe `docs/MCP.md`.

`td grok` schreibt `~/.threaddesk/grok-prompt.md` und zeigt den `grok --prompt-file`-Befehl. Grok wird nicht gestartet. Siehe `docs/GROK.md`.

`td gate` ist der lokale Tollgate-Wrap: Tageslimits, Cooldown, Freeze. Brainstorm bleibt frei. Das Tollgate-Produkt wird nicht importiert und nicht gestartet. Siehe `docs/TOLLGATE.md`.

`td dash` ist die lokale Tafel nach Status. Kein Server, kein Drag-and-Drop, kein Execute. Siehe `docs/DASHBOARD.md`.

`td gnom` schreibt das Chat-Paket für `POST /api/chat`. Gnom-Hub wird nicht gestartet und nichts gesendet. Siehe `docs/GNOM.md`.

## Prinzip

Brainstorm freely — Execute only when pressed. ThreadDesk bereitet vor. Gnom-Hub führt aus.
