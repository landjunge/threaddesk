# ThreadDesk Dashboard

Nur Ansicht. Schreibt lokale Dateien. Startet keine Agenten und keinen Server.

```bash
td dash              # Tafel im Terminal + HTML
td dash --all        # inkl. archivierte
td dash --open       # HTML im Browser öffnen
```

Dateien:

- `~/.threaddesk/dashboard.html`
- `~/.threaddesk/dashboard.json`

Spalten folgen dem Thread-Status: idea, active, paused, done. Kein Drag-and-Drop, kein Execute.

Titel und Notiz-Vorschau sind im HTML escaped. Volle Notizen liegen nicht im Dashboard.
