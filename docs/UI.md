# ThreadDesk UI Plan (HTMX + Alpine.js)

**Stand:** 15.08.2026  
**Status:** Phase 5 umgesetzt (Rename, Dateien, Prompt-Vorschau)  
**Kernprinzip:** ThreadDesk führt **niemals** etwas aus. Die UI bereitet nur vor und zeigt an.

## Phasen

### Phase 1–4 — erledigt
Lesen, Schreiben, Gate, Snapshots, Shortcuts, Pakete.

### Phase 5 – Kontext verdichten
- [x] Thread umbenennen
- [x] Dateipfade hinzufügen / entfernen
- [x] Prompt-Vorschau + optional speichern

## Harte Regeln

1. Jede Write-Aktion geht über `ThreadService`.
2. Die UI startet niemals gnom, grok oder einen Agenten.
3. Dateien sind nur gemerkte Pfade — kein Upload, kein Öffnen.
4. Prompt ist Vorschau. Kopieren ja, Starten nein.

Start:

```bash
pip install -e ".[ui]"
td serve
```
