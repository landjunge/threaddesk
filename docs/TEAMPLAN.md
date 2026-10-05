# ThreadDesk – Abschlussplan, 2. Oktober 2026

Für die anschließende Verbindung von Identität, Sync und Firmenzugriff gilt
[GOLDENRULES.MD](usability/GOLDENRULES.MD) vom 3. Oktober 2026. Das ist ein
Sicherheitsplan mit vorbereiteter Baufolge; seine neuen Mechanismen sind noch
nicht implementiert. Die folgende Abnahme betrifft die vorhandene lokale Ausgabe.

## Ziel und Geltungsbereich

Ein verständlicher lokaler Arbeitsplatz, der Kontext und Arbeitsstand zwischen
Mensch und KI erhält. Kein zweiter externer Orchestrator. Die lokale KI
bleibt ein gesonderter, optionaler Akteur innerhalb ihrer dokumentierten Grenzen.

Dieser Plan ersetzt den überholten Vier-Funktionen-MVP-Plan vom 14. August.
Code und aktuelle Abnahme: **PR #62**, Branch `feat/desktop-brand-icons`.
Konkrete Testzahlen und Build-Links stehen im PR, nicht in parallel gepflegten Kopien.

## Abschlussreihenfolge

1. Vorhandene Funktionen und gesamten Branch prüfen; keine funktionierenden Module neu bauen.
2. Team-Sync mit zwei echten Serverprozessen und echter Browserbedienung für JSON und SQLite abnehmen.
3. Private Notizen von freigegebenen Einträgen trennen; Raum, Gegenstelle und Schreibrolle prüfen.
4. Offline-/Neustartverhalten, Konflikterhalt und wiederholten Sync ohne Kopien nachweisen.
5. Lokale Oberfläche ohne CDN laden; App-Start und Datenerhalt absichern.
6. Windows-, Intel-Mac- und Apple-Silicon-Pakete mit bestehender Bildmarke bauen und ihre Selbsttests ausführen.
7. README aktualisieren, Quellen/Prüfsummen beilegen, ganze Testsuite zweimal ohne übersprungene Abnahmetests ausführen.
8. Ergebnis anhand des konkreten Commit-Standes dokumentieren. Keine automatische Veröffentlichung oder Übernahme nach main.

## Technische Grundsätze bleiben erhalten

Core, Storage, UI, Services und API bleiben getrennt. UI und Speicherung sind
austauschbar. Neue fachliche Funktionen gehören in ihre eigenen Module.
Code, Beispielmaterial und personenbezogene Arbeitsdaten bleiben getrennt.
Testdaten sind synthetisch und liegen ausschließlich in temporären Arbeitsbereichen.

## Reproduzierbare Prüfung

```sh
python -m pip install -e '.[dev,ui,browser]'
python -m playwright install chromium
python scripts/check_release_inputs.py
python -m pytest -q -ra
python -m pytest -q -ra
```

Für einen nativen Build auf der jeweiligen Plattform zuerst die Icons erzeugen
(`python -m pip install CairoSVG Pillow`, `python scripts/build_icons.py`), dann
`python -m pip install -e '.[ui,desktop]' pyinstaller` und
`pyinstaller --noconfirm --clean packaging/ThreadDesk.spec` ausführen.
Die GitHub-Builds erzeugen passende EXE-/DMG-Pakete sowie `.sha256` und `.build.json`.
Das macOS-Paket wird nur ad-hoc signiert, nicht als Apple-notarisiert ausgegeben.

## Nicht durch lokale CI bewiesen

- Start und Bedienung auf Daniels tatsächlichem Intel-Mac und seiner macOS-Version.
- Qualität, Antwortzeit und Ressourcenverbrauch des ausgewählten lokalen LLM mit echten Projektdaten.
- Produktiver Notion-Import; Notion bleibt bei dieser Arbeit unangetastet.
- Zusammenarbeit über einen externen Server, mehrere Haushalte oder eine öffentliche Server-Oberfläche.
- Native Linux- und Mobilpakete.

Diese Punkte bleiben offen und dürfen nicht aus grünen lokalen Tests als erledigt
abgeleitet werden. Der lokale HTTP-Sync ist keine Ende-zu-Ende-Verschlüsselung.
Der frühere Wunsch nach einem Wechsel zwischen 5–10 Threads in unter zwei Sekunden
bleibt ein Nutzerziel, keine ungeprüfte Leistungsbehauptung.

## Umsetzung der Nutzbarkeits-Abnahme, 2. Oktober 2026

PR #62 ist inzwischen nach `main` gemergt. Die nächste Ausgabe ergänzt eine
bedienbare Datenseite mit herunterladbaren, geprüften Sicherungen für JSON und
SQLite. Wiederherstellung öffnet einen getrennten Arbeitsbereich; das Original
bleibt erhalten. Die Auswahl bleibt über Neustarts erhalten und gilt für Desktop,
CLI und MCP. Die lokale Desktop-Adresse und Start-Sperre bleiben an die
Installation gebunden.

Die vom Nutzer beauftragte Auslieferung ersetzt die frühere Beschränkung auf
unveröffentlichte Build-Artefakte: Eine neue Versionsnummer wird als Release-Kandidat
veröffentlicht, sobald alle drei nativen Builds und die vollständige Testsuite
zweimal ohne Fehler oder übersprungene Tests durchgelaufen sind. Vor dem Upload
werden Dateien, Plattform, Architektur, Commit, Größe und Prüfsumme geprüft.
Bereits veröffentlichte Versionen werden nicht ersetzt.

Externe Agenten werden weiterhin über vorbereitete Übergaben angebunden. Die
lokale KI benötigt ein vom Nutzer ausgewähltes und vorhandenes Ollama-Modell.
Internet-Teamhosting bleibt außerhalb dieser lokalen Ausgabe.
