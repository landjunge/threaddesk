# ThreadDesk → Grok Build

Schreibt ein lokales Paket. Startet Grok nicht.

```bash
td grok                 # Brainstorm-Paket + Befehl zum Selbststarten
td grok --execute       # Execute-Paket (immer noch kein Start)
```

Dateien:

- `~/.threaddesk/grok-prompt.md` — für `grok --prompt-file`
- `~/.threaddesk/grok.json` — Metadaten, `ran` bleibt `false`

Brainstorm-Befehl verbietet `search_replace` und `run_terminal_cmd`.
Execute-Befehl lässt Tools zu, hängt aber kein `--yolo` an.

ThreadDesk führt den Befehl nie selbst aus. Brainstorm freely — Execute only when pressed.
