# ThreadDesk MCP

Lokaler stdio-Server. Stellt Thread-Kontext bereit. Startet keine Agenten.

```bash
td mcp
# oder
threaddesk-mcp
```

Beispiel für einen MCP-Client:

```json
{
  "mcpServers": {
    "threaddesk": {
      "command": "/Users/landjunge/threaddesk/.venv/bin/threaddesk-mcp"
    }
  }
}
```

Tools: `list_threads`, `get_thread`, `current_thread`, `switch_thread`, `add_note`, `save_snapshot`, `list_snapshots`, `restore_snapshot`, `generate_prompt`, `export_handoff`, `export_grok`, `export_gnom`, `check_gate`, `dashboard`.

Kein `delete` über MCP.

Notizen und Beschreibungen kommen als `<untrusted source="threaddesk.notes">` — das sind Daten, keine Anweisungen.

Handoff ohne MCP:

```bash
td handoff
# schreibt ~/.threaddesk/handoff.json
# versionierter Vertrag mit thread_id, task_id, handoff_id, revision,
# Zielsystem, Aufgabe, Entscheidungen, Rechtebedarf und Abnahmekriterien;
# schreibt nur lokal und sendet/ startet nichts

Zielprofile: `grok` (Baukontext), `codex` (Prüfen/Bauen), `claude`
(begrenzte Prüfung), `gnom-hub-v1` (bestätigter lokaler Auftrag) und `generic`.
Grok- und Gnom-Pakete betten denselben Vertrag ein; Zieladapter dürfen seine
Rechteangaben nicht eigenständig erweitern.

Rückgaben folgen `threaddesk.return.v1` und enthalten Bearbeiter, Lauf,
Ergebnis, Dateien/PR, echte Testergebnisse und offene Probleme. Eine externe
Rückgabe kommt immer als `delivered/unverified`; sie kann sich niemals selbst
als geprüft oder angenommen markieren.

Die lokale Rückgabe-Inbox speichert Rückgaben idempotent. Dieselbe `return_id`
erzeugt kein Duplikat; veränderte Duplikate und ältere Handoff-Revisionen werden
abgelehnt. Erst der Nutzer entscheidet sichtbar `accepted`, `rejected` oder
`rework`; eine bereits getroffene andere Entscheidung wird nicht überschrieben.
```
