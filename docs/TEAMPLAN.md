# ThreadDesk – Abschlussplan, 2. Oktober 2026

## Ziel und Geltungsbereich

Ein verständlicher lokaler Arbeitsplatz, der Kontext und Arbeitsstand zwischen
Mensch und KI erhält. Kein zweiter externer Orchestrator. Der lokale Hausmeister
bleibt ein gesonderter, optionaler Akteur innerhalb seiner dokumentierten Grenzen.

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

## Gesamtauftrag E01–E09, 20. Oktober 2026

Dieser Abschnitt führt den bestehenden Plan fort. Die aktuelle ausdrückliche
Beauftragung geht älteren Übergabeformulierungen vor; historische Nachweise
bleiben datiert erhalten. Vollständiger Originalplan: ThreadDesk-Thread
`6b5b73b9de36`, „Gesamtplan ThreadDesk & 4AllPass – 20.10.2026“, Revision 3.
Zehn geordnete Bridge-Anlagen ergeben 107935 UTF-8-Bytes, SHA256
`4b8ac493add0b76bd1a353d59d13152bbb5ec62bc956c1def9f1ccc1aa211ca8`.
Die vollständige Fach-API-Nachlese stimmt bytegenau überein. Im Thread steht
der erste Originalteil in der markierten Beschreibung, der Rest in den
Notizen; beide werden ohne zusätzliches Trennzeichen aneinandergefügt.
Gespräch `kira-gesamtplan-team-20261020-1031` und quittierte Übergabe
`7a7a268e-09c2-4a0f-a333-031cd7fc094c` gehören zum selben Auftrag. Ihre
Übernahme löst keinen zweiten CLI-Auftrag aus und bedeutet keine Fachabnahme.

Codex koordiniert und implementiert mit abgegrenzten nativen Teamaufgaben;
Grok prüft konkrete Commits unabhängig über sein zugeordnetes bestehendes
sichtbares Fenster. Groks nativer `spawn_subagent`-Modus ist praktisch belegt;
für RC11 startete er zwei abgegrenzte Prüfaufträge. Ihre Einzelresultate stehen
noch aus; Groks eigene unabhängige RC11-Prüfung ist bereits eingegangen. Kein Codex-Unteragent ersetzt diese unabhängige Prüfung. Neue
Hauptsitzungen oder ein Hintergrundersatz sind nicht vorgesehen. Änderungen
an gemeinsamen Dateien werden vorab eindeutig einem Bearbeiter zugeteilt.

| ID | Umfang / bestehende Zuordnung | Stand und nächster Schritt |
| --- | --- | --- |
| E01.1 | P00/R01, Quell-/Paket-/Arbeitsbestand | Teilbasis erfasst: ThreadDesk main `ce8b403`, 4AllPass main `905e6b5`; vorhandene M1/M2/Wissens-/Design-/RC3-Belege erhalten. Isolierte Tests und vollständige Claim-/Prüfzuordnung noch offen. |
| E01.2 | RC9/RC10, ST-01–ST-05 | Kira-Katalog-/Leseweg praktisch belegt; Codex-Bereitschaftsreparatur `2062055` mit 921 Gesamttests und anschließenden 172 gezielten Tests. Grok nahm nach eigenen 172 Tests begrenzt ab; RC11 ist kontrolliert aktiv, geladene Quelle/Konfiguration stimmen überein. Echter Kira→Original-Codex→Kira-Test bleibt offen. |
| E01.3 | Native Teams und verbindliche Übergaben | Codex-Team für Parser/Regressionen sowie Import/Client/Bestand eingesetzt; Ergebnisse zusammengeführt. Grok-Review `e4c91752-bd49-425d-a3ce-a1c8bd887dc4` wartete bei `desktop_locked` ohne Eingabe; nach Entsperren im zugeordneten Fenster authentifiziert empfangsquittiert, Grok-Urteil eingegangen: ship im geprüften RC11-Umfang. Ergebnisse seiner zwei nativen Unteragenten noch offen. Kein zweiter RC11-Reviewauftrag. |
| E02.1 | TD-01, F1/F2 | Kandidat auf main `ce8b403`: gebundene Quellen und JSON-WAL-Controlpfade, manifestgebundener Restore, exklusive Zieldateien und Veröffentlichung. Unabhängige Codex-Gegenproben korrigiert; abschließend 170 Integrationstests bestanden. Grok und native Windows-/Linux-CI offen; keine Live-Installation. |
| E02.2 | TD-02 | Kandidat im separaten TD02-Worktree: lokale Host-/Origin-/Sitzungs-/CSRF-Grenze, drei exakte Room-Ausnahmen, echte Browser-/Zwei-Prozess-Gegenproben. Zusätzliche Codex-Prüfung fand Erstinitialisierung beim GET; eng zu korrigieren. Grok und Integration offen. |
| E02.3–4 | AP-01/AP-02/F4 | In 4AllPass `ROADMAP.md`: AP01 Dokumente/Template in DraftPR229 (HEAD `ab1aba3`, identischer Quellbaum zu Reviewpin `4bfc476`); AP02 sofortige413 im DraftPR230, `3951697`, 156 Backendtests bestanden/1 expliziter Postgres-Migrationstest ohne isoliertes Postgres ausgenommen. Grok-Review `e5db3654` queued, nicht als empfangen behauptet. |
| E03 | P01–P05, R02–R07/R12, AP-04 | Offen: Kryptografie, Snapshot, Konto/Sitzung, Geräte, Recovery und belastbarer Identitätsvertrag. Vorhandene Tests ersetzen keine Bereichsabnahme. |
| E04 | P06–P08/P11–P12, R08–R11/R15–R17, AP-03 | Offen: Browser-/Desktop-/native Nutzerwege und Paketnachweise am tatsächlichen Kandidaten. |
| E05 | UI-01, zugehöriger TD-08-Umfang | Offen: gemeinsame kompakte App-Leiste, vorhandene Icons, bestätigte frische Verbindungen; nur 4AllPass bei bestätigtem Unlock sehr dezenter Puls. |
| E06 | TD-03–TD-06/TD-08, AP-04 | Offen: Projektrollen, atomarer Transfer, Team-Sync, projekt-/thread-/revisions-/laufgebundene Agentenaufträge. |
| E07 | AP-05–AP-07, P09/R13–R14 | Offen: begrenzte Freigaben, tatsächliche Hostgrenze und genau eine freigegebene reale Anbieteroperation; kein synthetischer Test als Produktionsbeweis. |
| E08 | TD-07 | Offen: berechtigte FTS5-Inhaltssuche, getrennter optionaler Bridge-Dateiindex, benannte Datenmengen/Leistungsmessung. |
| E09 | TD-09/AP-08, P10–P12, R01–R17, H1–H6, T01–T22 | Offen: einschlägige Nachweise zuordnen, Nutzer-/Modulwege abnehmen, geprüfte Pakete nach bestehenden Release-Gates ausliefern. |

Stand dieser Einpflege: E01 ist noch nicht abgeschlossen. Die Mac-Sperre
verhinderte zunächst die sichtbare Grok-Prüfung; die RC11-Prüfung wurde nach
Entsperren abgeschlossen. Der Mac ist erneut gesperrt. Der auf 15 Minuten
begrenzte Altfall-Abgleich beobachtete kein Entsperren und endete ohne Versuch,
Eingabe oder Return; der Originaltest bleibt `unknown`, keine Wiederholung.
Die praktische Codex-Terminalabnahme bleibt offen, isolierte E02-Arbeit läuft
unabhängig weiter. Der öffentliche Handy-/Tunnelweg
ist auf Daniels Wunsch zurückgestellt und wird hierbei nicht verändert.
Restrolle nach Leitungstransfer, genaue Manager-/Abnahmerechte, Stellvertretung
sowie Executor-Betriebsprofil/erste reale Operation benötigen vor dem jeweiligen
Ausbau eine fachliche Entscheidung; sie blockieren lokale Reparaturen nicht.

Jeder folgende Unterpunkt ergänzt hier Commit, Dateien, konkrete Tests,
unabhängiges Grok-Urteil, verbleibende Grenze und nächsten Schritt. Status bleiben
offen / in Arbeit / in Prüfung / blockiert mit Ursache / abgeschlossen im benannten
Umfang. Paketbau, Installation, Aktivierung und Produktfreigabe sind eigene Belege.
