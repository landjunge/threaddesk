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
Gnom-Pakete verwenden `threaddesk.gnom-handoff.v1`. Sie tragen den
versionierten Handoff-Vertrag, `preview_required=true` und beginnen als
`pending_user_confirmation`. ThreadDesk markiert sie weder als gesendet noch
als ausgeführt. Gnom-Hub muss den Kontext vor jeder Übernahme sichtbar zeigen.

Nach der sichtbaren Übernahme bindet ThreadDesk eine Gnom-`job_id` dauerhaft
an `thread_id`, `task_id`, `handoff_id` und Handoff-Revision. Statusereignisse
haben eine eigene `event_id`; identische Wiederholungen sind No-ops, veränderte
Duplikate werden abgelehnt.

Der lokale Rückkanal akzeptiert ausschließlich
`threaddesk.gnom-callback.v1` mit bekannten Feldern und den Zuständen
`started`, `question`, `blocked`, `error`, `delivered` oder `cancelled`.
Eine Lieferung wird nur als `delivered/unverified` in die Review-Inbox gelegt;
sie verändert niemals direkt bestätigtes Wissen.

Unterbrechungsregeln: Job- und Ereignisspeicher überleben Neustarts. Jede
Callback-Nachricht muss zur gebundenen Handoff-Revision passen. Ereignisse mit
älterem Zeitpunkt werden abgelehnt. Nach `error`, `delivered` oder `cancelled`
ist der Job terminal; verspätete Folgeereignisse können ihn nicht wieder öffnen.
