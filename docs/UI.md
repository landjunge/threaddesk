# ThreadDesk UI Plan (HTMX + Alpine.js)

**Stand:** 15.08.2026  
**Status:** Phase 3 umgesetzt (`td serve` liest und schreibt)  
**Kernprinzip:** ThreadDesk führt **niemals** etwas aus. Die UI bereitet nur vor und zeigt an.

## 1. Ziele

- Threads, Kontext, Snapshots und Gate sichtbar und bedienbar machen
- Schreib-Aktionen (Notiz, Status, Snapshot, Switch, Freeze) direkt aus der UI
- CLI und UI parallel nutzbar
- 100 % lokal (`127.0.0.1`), kein Build-Step, keine Cloud

## 2. Non-Goals

- Kein Agent-Start / kein Execute / kein automatisches Handoff
- Kein Login, kein Multi-User
- Kein Drag-and-Drop in der ersten Version (kommt optional später)
- Kein schweres Frontend-Framework (React, Vue, Svelte etc.)

## 3. Tech-Stack

| Schicht       | Technologie              | Begründung                          |
|---------------|--------------------------|-------------------------------------|
| Backend       | FastAPI + Jinja2         | Passt zu Python, liefert HTML-Fragmente |
| Interaktion   | HTMX                     | Server-getriebene Updates, wenig JS |
| Lokaler State | Alpine.js                | Dropdowns, Loading-States, Toggles  |
| Styling       | Einfaches CSS (später optional Tailwind) | Schlank und dunkel                 |
| Start         | `td serve` / `td ui`     | Neuer CLI-Befehl                    |

## 4. Projektstruktur (neue Dateien)

```
src/threaddesk/
├── ui/
│   ├── cli.py                 # bestehend + neuer "serve"-Befehl
│   ├── server.py              # FastAPI App
│   ├── templates/
│   │   ├── base.html
│   │   ├── index.html
│   │   └── partials/
│   │       ├── thread_list.html
│   │       ├── thread_detail.html
│   │       ├── notes.html
│   │       ├── snapshots.html
│   │       └── gate.html
│   └── static/
│       ├── style.css
│       └── app.js
```

Alle Schreib- und Lesevorgänge laufen weiterhin **nur** über `ThreadService`.

## 8. Implementierungs-Phasen

### Phase 1 – Server-Fundament — erledigt
### Phase 2 – Lesen — erledigt

### Phase 3 – Schreiben
- [x] Notiz setzen / anhängen
- [x] Status ändern
- [x] Snapshot speichern & laden
- [x] Neuen Thread anlegen
- [x] Gate Freeze
- [x] Beschreibung speichern

### Phase 4 – Polish
- [ ] Tastatur-Shortcuts
- [ ] Schöne, dunkle Optik
- [ ] Loading- und Erfolgs-Feedback
- [ ] Bestätigungen für destruktive Aktionen

Start:

```bash
pip install -e ".[ui]"
td serve
```

**Nächster Schritt:** Phase 4 — Shortcuts, Feedback, Bestätigungen.
