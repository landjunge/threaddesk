# ThreadDesk Gate (Tollgate-Wrap)

Lokaler Loop- und Tages-Schutz. Importiert das Tollgate-Produkt nicht. Startet keinen Server.

```bash
td gate                 # Status
td gate check           # dürfte Execute jetzt vorbereitet werden?
td gate freeze
td gate unfreeze
td gate set --max-execute-day 10 --cooldown 30
```

Gesperrt werden nur **Execute-Pakete** (`td grok --execute`) und **Handoffs**. Brainstorm, Prompts, Snapshots und Thread-CRUD bleiben frei.

Defaults: 30 Execute / Tag, 8 pro Thread, 15s Cooldown, Freeze aus.

Daten: `~/.threaddesk/gate.json`. Keine API-Keys.

MCP hat `check_gate` (lesen). Kein freeze/set über MCP.

Das echte Tollgate unter `~/tollgate` bleibt unverändert. Dieser Wrap ist nur die ThreadDesk-Seite: vorbereiten oder ablehnen, nie ausführen.
