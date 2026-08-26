# ThreadDesk

Lokale Control-Layer vor Gnom-Hub. Speichert Threads und Kontext. Führt nichts aus.

**MVP v0.1:** Threads · persistenter Kontext · Switcher · Snapshots.

## How this is built / Wie dieses Projekt entsteht

**System Designer & Product Architect** — Daniel Filipek (landjunge)

Ich arbeite anders: Ich entwickle Systeme und Produkte mit KI als technischem Partner.

Meine Stärke liegt darin, Probleme zu erkennen, Systeme in eigenständige Werkzeuge zu zerlegen und klare Grenzen und Schnittstellen zu definieren. Produktvision, Prioritäten und Architekturentscheidungen kommen von mir. KI ist der technische Partner für Implementierung, Tests und Dokumentation.

Ich bin kein klassischer Softwareentwickler und kein Security-Spezialist. Die technische Umsetzung entsteht gemeinsam mit KI und muss – besonders bei sicherheitskritischen Projekten – überprüfbar sein.

Was ich einbringe: Idee, Systemdenken, Anforderungen, gewünschtes Verhalten, klare Grenzen.  
Was überprüfbar sein muss: der Code, die Specs, die Tests. Reviews sind willkommen.

Open Source und öffentlich entwickelt. Kritik, Tests und Beiträge sind willkommen.

ThreadDesk speichert Kontext und führt **nichts** aus. Die Grenze *ist* das Produkt.

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
td serve                      # lokale UI auf http://127.0.0.1:8765 (nichts ausführen)
td gnom                       # gnom-hub-v1 Send-Paket + curl, nichts senden
td gnom --execute             # plus /api/execute, immer noch kein POST
```

Wechsel stellt den vollen Kontext wieder her. Kein Agent wird gestartet.

Die optionale UI (`td serve`) braucht `pip install -e ".[ui]"` (FastAPI + Jinja2). Sie spricht nur mit `ThreadService`. Siehe `docs/UI.md`.

Prompt-Generator ist lokal (Vorlage, kein API-Call). Er bereitet Text vor. Es wird niemand angerufen.

MCP stellt nur Thread-Daten bereit. Kein `delete`, keine Agent-Starts. Notizen kommen als `<untrusted>`. Siehe `docs/MCP.md`.

`td grok` schreibt `~/.threaddesk/grok-prompt.md` und zeigt den `grok --prompt-file`-Befehl. Grok wird nicht gestartet. Siehe `docs/GROK.md`.

`td gate` ist der lokale Tollgate-Wrap: Tageslimits, Cooldown, Freeze. Brainstorm bleibt frei. Das Tollgate-Produkt wird nicht importiert und nicht gestartet. Siehe `docs/TOLLGATE.md`.

`td dash` ist die lokale Tafel nach Status. Kein Server, kein Drag-and-Drop, kein Execute. Siehe `docs/DASHBOARD.md`.

`td gnom` schreibt das Chat-Paket für **gnom-hub-v1** (`POST /api/chat` mit `text`). Der Hub wird nicht gestartet und nichts gesendet. Siehe `docs/GNOM.md`.

## Prinzip

Brainstorm freely — Execute only when pressed. ThreadDesk bereitet vor. Gnom-Hub führt aus.
