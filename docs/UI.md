# ThreadDesk UI Plan (HTMX + Alpine.js)

**Stand:** 15.08.2026  
**Status:** Phase 4 umgesetzt (`td serve` liest, schreibt, Pakete, Shortcuts)  
**Kernprinzip:** ThreadDesk führt **niemals** etwas aus. Die UI bereitet nur vor und zeigt an.

## Phasen

### Phase 1–3 — erledigt
Lesen, Schreiben, Gate, Snapshots.

### Phase 4 – Polish
- [x] Tastatur-Shortcuts
- [x] Schöne, dunkle Optik
- [x] Loading- und Erfolgs-Feedback
- [x] Bestätigungen für destruktive Aktionen
- [x] Handoff- / Gnom-Paket schreiben (ohne Start)

## Harte Regeln

1. Jede Write-Aktion geht über `ThreadService`.
2. Die UI startet niemals gnom, grok oder einen Agenten.
3. Handoff / Gnom bleiben „Paket schreiben + Befehl anzeigen“.
4. CLI bleibt parallel nutzbar.

Start:

```bash
pip install -e ".[ui]"
td serve
```

**Nächster Schritt:** optional Dateien in der UI, Rename, Prompt-Vorschau.
