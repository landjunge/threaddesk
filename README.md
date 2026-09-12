<p align="center"><img src="brand/mark.svg" width="180" alt="ThreadDesk Bildmarke"></p>
<p align="center"><img src="brand/wordmark.svg" width="520" alt="ThreadDesk"></p>
<p align="center"><a href="https://github.com/landjunge/threaddesk/releases/tag/preview"><img src="brand/download-button.svg" width="320" alt="ThreadDesk herunterladen"></a></p>

<p align="center"><strong>Ein Arbeitsplatz, der den Stand deiner KI-Projekte behält.</strong></p>

ThreadDesk speichert Threads, Notizen, Dateien und Snapshots. Es führt bewusst nichts aus.

### 👤 [Für Nutzer – einen Thread beginnen](#für-nutzer)

### 🛠️ [Für Entwickler – CLI, MCP und Aufbau](#für-entwickler)

---

## Für Nutzer

### Einfach erklärt

Beim Arbeiten mit KI springt man oft zwischen Ideen und Projekten. Später weiß niemand mehr genau, was entschieden wurde oder wo man aufgehört hat.

ThreadDesk merkt sich diesen Stand. Jeder Arbeitsbereich wird zu einem eigenen Thread.

> **Was ist der Stand?**

### Was du davon hast

- Jede Idee erhält ihren eigenen dauerhaften Kontext.
- Du kannst zwischen Projekten wechseln und später weitermachen.
- Notizen, Dateien und Snapshots bleiben beim Thread.
- Handoffs bereiten Arbeit für andere Werkzeuge vor.
- ThreadDesk startet niemals selbst einen Agenten.

### In drei Schritten

1. **Thread anlegen** – eine Idee oder Aufgabe benennen.
2. **Stand festhalten** – Notizen, Dateien und Status ergänzen.
3. **Weitergeben** – bei Bedarf ein Handoff für Gnom-Hub-V1 erzeugen.

### Heutiger Stand – ehrlich

| Bereich | Aktueller Stand |
|---|---|
| Threads | Anlegen, wechseln, archivieren und löschen |
| Kontext | Notizen, Dateien, History und Snapshots |
| Daten | JSON unter ~/.threaddesk; lokal |
| Oberfläche | CLI, lokale Tafel und optionale Weboberfläche |
| Übergaben | Vorbereitete Pakete für Grok und Gnom-Hub-V1 |
| Grenze | Kein Agentenstart und kein verstecktes Execute |

[Produktseite](https://threaddesk.netzwerkpunkt.de/)

---

## Einfach starten

### macOS

1. Oben auf **ThreadDesk herunterladen** klicken.
2. **ThreadDesk-macOS.dmg** laden und ThreadDesk nach „Programme“ ziehen — fertig. Die Ausgabe unterstützt Intel-Macs (i7) nativ.

Falls macOS den Doppelklick blockiert: Rechtsklick auf die Datei → **Öffnen**.

### Windows

1. Oben auf **ThreadDesk herunterladen** klicken.
2. **ThreadDesk-Windows.exe** laden und doppelklicken — fertig.

### Ein Terminal-Befehl

~~~sh
python3 start.py
~~~

Die Desktop-Downloads enthalten Python und alle benötigten Bestandteile. Für den Terminal-Befehl ist Python 3.9 oder neuer erforderlich.

Ein erster Thread in der Oberfläche:

Klicke auf „Neuer Thread“, gib deiner Idee einen Namen und speichere den ersten Stand.

---

## Für Entwickler

ThreadDesk ist eine lokale Control-Layer vor Gnom-Hub-V1. Die Grenze ist Teil des Produkts: Alle Übergaben werden vorbereitet, aber nicht automatisch gesendet oder ausgeführt.

### Wichtige Befehle

| Aufgabe | Befehl |
|---|---|
| Threads anzeigen | td list |
| Thread wechseln | td switch 1 |
| Status setzen | td status active |
| Snapshot speichern | td snap save "vor-umbau" |
| Prompt vorbereiten | td prompt |
| Handoff schreiben | td handoff |
| Lokale Oberfläche | td serve |
| MCP-Server | td mcp |
| Ausführung sperren | td gate freeze |
| Sprache umschalten | td --lang en list |

### Sprache

ThreadDesk spricht Deutsch und Englisch — Oberfläche und Kommandozeile.

| Weg | Beispiel |
|---|---|
| Einmalig | `td --lang en list` |
| Dauerhaft | `export THREADDESK_LANG=en` |
| Automatisch | aus `LC_ALL`, `LC_MESSAGES` oder `LANG` |
| Oberfläche | Schalter oben rechts, merkt sich die Wahl ein Jahr |

Ohne Angabe ist Deutsch die Voreinstellung. Die Gliederungswörter der
Kommandozeilenhilfe (`usage:`, `options:`) kommen aus Python selbst und
bleiben englisch.

### Sprachebene: Klartext oder Fachsprache

Unabhängig von Deutsch/Englisch gibt es zwei Sprachebenen. **Klartext ist der
Normalfall, Fachsprache ist zuschaltbar** — nie umgekehrt. Wer die Begriffe
kennt, schaltet sie ein; wer sie nicht kennt, wird nicht mit ihnen überfahren.

| Weg | Beispiel |
|---|---|
| Einmalig | `td --mode expert gate` |
| Dauerhaft | `export THREADDESK_MODE=expert` |
| Oberfläche | Schalter oben rechts neben DE/EN, merkt sich die Wahl ein Jahr |

| Klartext (Standard) | Fachsprache |
|---|---|
| Schranke · Übergabe · Zwischenstände | Gate · Paket · Snapshots |
| `geschlossen: nein` · `heute losgeschickt` · `wartezeit: 15s` | `frozen: nein` · `execute heute` · `cooldown: 15s` |

Die Sprachebene wird **nicht** aus dem Browser oder der Umgebung geraten:
Klartext gilt für alle, bis jemand etwas anderes sagt.

Für die manuelle Entwicklerinstallation: `python3 -m pip install -e ".[dev,ui]"`. Daten liegen unter `~/.threaddesk/`.

### Die gemeinsamen Regeln der NetzwerkPunkt-Werkzeuge

ThreadDesk, 4AllPass und TollGate teilen sich Aussehen und Sprachregeln.
Wer ein neues Werkzeug baut, übernimmt dieselben Werte — sie sind nicht
Geschmack, sondern nachschlagbare Standards. **4AllPass ist die Vorlage.**

**Farben** (gleich in allen Werkzeugen)

| Token | Wert | Wofür |
|---|---|---|
| `--bg` | `#121316` | Grundfläche |
| `--bg-panel` | `#1a1b1f` | Fläche |
| `--bg-card` | `#1e1f24` | Karte |
| `--fg` | `#e2e4e9` | Text |
| `--fg-muted` | `#8b909a` | Nebentext |
| `--border` | `#2e3138` | Trennlinie zwischen Flächen (Deko) |
| `--border-strong` | `#5f646f` | **Kante von Bedienelementen** |
| `--accent` | `#8f98a8` | Akzent |
| `--ok` / `--warn` / `--err` | `#3d9b6a` / `#c9a227` / `#dc7070` | Zustände |

**Form und Größe**

- `border-radius: 0` — überall. Rund nur, wo die Form etwas *bedeutet*
  (Kartensymbole, Fortschrittsring, Statuspunkt), mit Begründung im Code.
- Genau vier Schriftgrößen: **13 / 16 / 20 / 25 px**. 16px Grundgröße wie für
  Fließtext im Web empfohlen, die Stufen im Verhältnis 1.25 (große Terz).
  Andere Tokens werden gelöscht, nicht nur gemieden.
- Abstände im 8er-Raster: 4 / 8 / 12 / 16 / 24 / 32.
- **Genau zwei Größen für Bedienelemente**, mehr gibt es nicht:
  `--control: 40px` für den Regelfall (Knopf, Eingabefeld, Auswahlmenü) und
  `--control-sm: 32px` für dichte Zeilen und Chips. Beide liegen auf dem
  8er-Raster. Knopf, Eingabefeld und Auswahlmenü sind gleich hoch.
- Unter `@media (pointer: coarse)` werden alle Ziele **44px**
  (`--control-touch`). Das ist keine dritte Größe, sondern dieselben
  Elemente unter einem anderen Eingabegerät — die Zahl kommt von Apple und
  Material. Der Zeiger ist das richtige Signal, **nicht** die Fensterbreite:
  ein schmales Desktop-Fenster ist kein Finger. WCAG 2.2 (2.5.8) verlangt
  als Minimum 24px; alle drei Werte liegen darüber.
- Kontrast: **4.5:1** für Text, **3:1** für alles andere, was etwas bedeutet
  (WCAG 2.2, 1.4.3 und 1.4.11).
- Auswahlmenüs setzen `appearance: none` und zeichnen ihren Pfeil selbst —
  sonst malt das Betriebssystem das Menü, unter Windows mit 3D-Effekt.
- Schrift: die des Betriebssystems, nichts nachladen.

**Sprache**

- Jedes Werkzeug ist von Anfang an **deutsch und englisch**. Nachrüsten ist
  teuer. Sichtbarer Text gehört in einen Katalog, nie direkt ins Template.
- Immer **eine** Sprache zur Zeit, nie beide nebeneinander. Umschalter im Kopf.
- Auflösung: `?lang=` → Cookie → `Accept-Language` → Standard.
- Dazu die zwei Sprachebenen: **Klartext ist der Normalfall, Fachsprache ist
  zuschaltbar.** Eine Fachfassung hängt als eigener Katalogeintrag am selben
  Schlüssel, getrennt durch `#expert` (kein Punkt — sonst wäre
  `register.expert` die Fachfassung von `register`). Fehlt die Fachfassung,
  bleibt der Klartext stehen.
- Jede Beschriftung sagt, was passiert. Jedes Feld sagt, wofür es da ist.
  Keine Abkürzung ohne Auflösung. Fehlermeldungen nennen den nächsten Schritt.
- Eigennamen werden nicht übersetzt: ThreadDesk, TollGate, 4AllPass,
  Gnom-Hub-V1, Grok, Codex, Thread, MCP.

**Fallstrick**, der zweimal zugeschlagen hat: `argparse` baut die Hilfetexte
beim *Anlegen* des Parsers, nicht beim Parsen. `--lang` und `--mode` müssen
deshalb vorher von Hand aus `argv` gelesen werden, sonst ist
`td --mode expert --help` wieder Klartext.

### Wie dieses Projekt entsteht

**System Designer & Product Architect: Daniel Filipek (landjunge)**

Produktvision, gewünschtes Verhalten und Grenzen kommen von mir. KI unterstützt Implementierung, Tests und Dokumentation. Code und Verhalten müssen überprüfbar bleiben.

### Dokumentation

- [Benutzeroberfläche](docs/UI.md)
- [MCP](docs/MCP.md)
- [Grok-Handoff](docs/GROK.md)
- [TollGate-Grenze](docs/TOLLGATE.md)
- [Gnom-Hub-V1-Handoff](docs/GNOM.md)

---

**ThreadDesk beantwortet eine Frage: Was ist der Stand?**
Teil von [NetzwerkPunkt](https://netzwerkpunkt.de/) – eigenständig, local-first und ohne versteckte Ausführung.
