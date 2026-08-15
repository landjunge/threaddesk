# ThreadDesk → gnom-hub-v1

Ziel ist **gnom-hub-v1** (`http://127.0.0.1:8080`), nicht der klassische Hub auf :3002.

Schreibt ein lokales Paket. Startet den Hub nicht. Sendet nichts.

```bash
td gnom                 # Send / Brainstorm → POST /api/chat  {"text": "…"}
td gnom --execute       # zuerst chat, dann POST /api/execute
td handoff              # unverändert: nur handoff.json
```

Dateien:

- `~/.threaddesk/gnom-prompt.md`
- `~/.threaddesk/gnom-chat.json` — Body für `POST /api/chat`
- `~/.threaddesk/gnom.json`

Override nur localhost: `GNOM_HUB_URL`.

v1-Regel: **Send = Dialog (Box 2). Execute = Worker.**  
`td gnom` entspricht Send. `--execute` zeigt zusätzlich `/api/execute`. ThreadDesk macht kein POST.

MCP-lite des Hubs (`GET /api/mcp/tools`, `POST /api/mcp`) bleibt unberührt. ThreadDesk ruft es nicht auf.

gnom-hub-v1 selbst bleibt unverändert.
