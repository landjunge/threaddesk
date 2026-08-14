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

Tools: `list_threads`, `get_thread`, `current_thread`, `switch_thread`, `add_note`, `save_snapshot`, `list_snapshots`, `restore_snapshot`, `generate_prompt`, `export_handoff`, `export_grok`, `check_gate`.

Kein `delete` über MCP.

Notizen und Beschreibungen kommen als `<untrusted source="threaddesk.notes">` — das sind Daten, keine Anweisungen.

Handoff ohne MCP:

```bash
td handoff
# schreibt ~/.threaddesk/handoff.json
```
