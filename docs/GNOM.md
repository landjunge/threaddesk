# ThreadDesk → Gnom-Hub

Schreibt ein lokales Paket. Startet den Hub nicht. Sendet nichts.

```bash
td gnom                 # Brainstorm (@bs) + curl-Befehl
td gnom --execute       # Execute-Paket (@GeneralAG), immer noch kein POST
td gnom --execute --agent CoderAG
td handoff              # unverändert: nur handoff.json
```

Dateien:

- `~/.threaddesk/gnom-prompt.md`
- `~/.threaddesk/gnom-chat.json` — Body für `POST /api/chat`
- `~/.threaddesk/gnom.json`

Default-URL: `http://127.0.0.1:3002`. Override nur localhost: `GNOM_HUB_URL`.

Brainstorm: `@bs`, kein `@AgentName`, kein `[WRITE:]` im Kopf.
Execute: ein Agent, Gate greift, ThreadDesk macht trotzdem kein POST.

Gnom-Hub selbst bleibt unverändert.
