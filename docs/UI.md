# ThreadDesk UI Plan (HTMX + Alpine.js)

**Stand:** 15.08.2026  
**Status:** Phase 1 bereit zum Start  
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
│       └── app.js             # nur Alpine-Initialisierung falls nötig
```

Alle Schreib- und Lesevorgänge laufen weiterhin **nur** über `ThreadService`.

## 5. UI-Layout

```
┌──────────────────┬──────────────────────────────────────────────────────┐
│  Thread-Liste    │  Aktueller Thread                          │
│  (links)         │  - Titel + Status                          │
│                  │  - Beschreibung                            │
│  [Neu]           │  - Notizen (editierbar)                    │
│  • Thread A *    │  - Dateien                                 │
│  • Thread B      │  - Snapshots                               │
│  • ...           │  - Aktionen: Snapshot speichern, etc.      │
│                  │                                            │
│  Gate-Status     │  Gate-Freeze Toggle                        │
└──────────────────┴──────────────────────────────────────────────────────┘
```

## 6. Wichtige Endpunkte (HTML-Fragmente)

| Methode | Pfad                        | Zweck                              | HTMX-Ziel                  |
|---------|-----------------------------|------------------------------------|----------------------------|
| GET     | `/`                         | Komplette Seite                    | -                          |
| GET     | `/partials/threads`         | Thread-Liste neu rendern           | `#thread-list`             |
| POST    | `/threads`                  | Neuen Thread anlegen               | `#thread-list` + Detail    |
| POST    | `/threads/{id}/switch`      | Thread aktivieren                  | ganze rechte Seite         |
| POST    | `/threads/{id}/note`        | Notiz setzen / anhängen            | `#notes`                   |
| POST    | `/threads/{id}/status`      | Status ändern                      | Liste + Detail             |
| POST    | `/threads/{id}/snapshot`    | Snapshot speichern                 | `#snapshots`               |
| POST    | `/snapshots/{id}/restore`   | Snapshot laden                     | rechte Seite               |
| GET     | `/partials/gate`            | Gate-Status                        | `#gate`                    |
| POST    | `/gate/freeze`              | Freeze umschalten                  | `#gate`                    |

Alle POST-Endpunkte geben passende HTML-Fragmente zurück (nicht nur JSON).

## 7. HTMX + Alpine.js Muster

**HTMX-Beispiele:**
```html
<!-- Thread wechseln -->
<button hx-post="/threads/{{ id }}/switch"
        hx-target="#main"
        hx-swap="innerHTML">
  {{ title }}
</button>

<!-- Notiz speichern -->
<form hx-post="/threads/{{ id }}/note"
      hx-target="#notes"
      hx-swap="innerHTML">
  ...
</form>
```

**Alpine.js-Beispiele:**
- Loading-State während Requests
- „Notiz wurde gespeichert“-Feedback
- Gate-Freeze Toggle (optimistisches UI + Server-Bestätigung)
- Einfache Bestätigungs-Dialoge (Archive / Delete)

## 8. Implementierungs-Phasen

### Phase 1 – Server-Fundament
- [ ] `ui/server.py` mit FastAPI anlegen
- [ ] `td serve` Befehl in der CLI registrieren
- [ ] `base.html` + `index.html` (statisches Gerüst)
- [ ] Ein Endpunkt `/partials/threads` der die Liste liefert
- [ ] Server startet auf `127.0.0.1:8765`

### Phase 2 – Lesen funktioniert
- [ ] Thread-Liste links
- [ ] Aktueller Thread rechts (read-only)
- [ ] Gate-Status anzeigen

### Phase 3 – Schreiben
- [ ] Notiz setzen / anhängen
- [ ] Status ändern
- [ ] Snapshot speichern & laden
- [ ] Neuen Thread anlegen
- [ ] Gate Freeze

### Phase 4 – Polish
- [ ] Tastatur-Shortcuts
- [ ] Schöne, dunkle Optik
- [ ] Loading- und Erfolgs-Feedback
- [ ] Bestätigungen für destruktive Aktionen

## 9. Harte Regeln (nicht verhandelbar)

1. Jede Write-Aktion geht über `ThreadService` → Gate-Checks bleiben aktiv.
2. Die UI startet **niemals** gnom, grok oder irgendeinen Agenten.
3. Handoff / Grok / Gnom bleiben „Paket schreiben + Befehl anzeigen“.
4. CLI muss parallel weiter funktionieren.
5. Alles bleibt unter `~/.threaddesk/`.
6. Kein externer Zugriff – nur `localhost`.

## 10. Erste konkrete nächste Schritte

1. `docs/UI.md` mit diesem Plan anlegen ✅
2. FastAPI als optionale Dependency in `pyproject.toml` aufnehmen
3. `src/threaddesk/ui/server.py` anlegen und `td serve` verdrahten
4. Minimales `index.html` + Thread-Listen-Partial

---

**Nächster Schritt:** Phase 1 umsetzen (Server + `td serve` + minimales HTML).
