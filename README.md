# ThreadDesk

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
3. **Weitergeben** – bei Bedarf ein Handoff für gnom-hub-v1 erzeugen.

### Heutiger Stand – ehrlich

| Bereich | Aktueller Stand |
|---|---|
| Threads | Anlegen, wechseln, archivieren und löschen |
| Kontext | Notizen, Dateien, History und Snapshots |
| Daten | JSON unter ~/.threaddesk; lokal |
| Oberfläche | CLI, lokale Tafel und optionale Weboberfläche |
| Übergaben | Vorbereitete Pakete für Grok und gnom-hub-v1 |
| Grenze | Kein Agentenstart und kein verstecktes Execute |

[Produktseite](https://threaddesk.netzwerkpunkt.de/)

---

## Installation

~~~sh
git clone https://github.com/landjunge/threaddesk.git
cd threaddesk
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
~~~

Ein erster Thread:

~~~sh
td new "Meine Idee"
td note "Das ist der aktuelle Stand"
td current
td snap save "erster Stand"
~~~

---

## Für Entwickler

ThreadDesk ist eine lokale Control-Layer vor gnom-hub-v1. Die Grenze ist Teil des Produkts: Alle Übergaben werden vorbereitet, aber nicht automatisch gesendet oder ausgeführt.

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

Die optionale Oberfläche benötigt `pip install -e ".[ui]"`. Daten liegen unter `~/.threaddesk/`.

### Wie dieses Projekt entsteht

**System Designer & Product Architect: Daniel Filipek (landjunge)**

Produktvision, gewünschtes Verhalten und Grenzen kommen von mir. KI unterstützt Implementierung, Tests und Dokumentation. Code und Verhalten müssen überprüfbar bleiben.

### Dokumentation

- [Benutzeroberfläche](docs/UI.md)
- [MCP](docs/MCP.md)
- [Grok-Handoff](docs/GROK.md)
- [Tollgate-Grenze](docs/TOLLGATE.md)
- [gnom-hub-v1-Handoff](docs/GNOM.md)

---

**ThreadDesk beantwortet eine Frage: Was ist der Stand?**
Teil von [Netzwerkpunkt](https://netzwerkpunkt.de/) – eigenständig, local-first und ohne versteckte Ausführung.
