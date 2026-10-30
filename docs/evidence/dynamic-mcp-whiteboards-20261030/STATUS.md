# Dynamisches MCP und Whiteboards · 30. Oktober 2026

Ausgangsstand: `main d7e30c1`. Vorhandener sauberer Worktree wiederverwendet; die offenen Änderungen im älteren Hauptverzeichnis bleiben unberührt. Drei getrennte Teilaufträge wurden tatsächlich übernommen: dynamischer MCP-Adapter, Whiteboard/Graph sowie unabhängige Inventar- und Codeprüfung. Die isolierte Koordination verwendet ein echtes ThreadDesk-Whiteboard und lokale 60-Sekunden-Feedbacktimer; keine produktiven Nutzerdaten dienen als Testfixture.

## Inventar und Umsetzung

Vorhandene Registry statt zweiter Funktionsliste: vorher 127, jetzt 141 Fachbefehle. [inventory.json](inventory.json) enthält jeden Befehl mit Wirkung, Scope, Verfügbarkeit, Operations-/Revisionsanforderung und Transporten. Für JSON sind 133, für SQLite 136 registrierte Befehle über MCP zulässig. Drei Migrationen benötigen SQLite; `search.*` und `server_sync.owner_reference` behalten ihre lokale Eigentümergrenze. Unzulässige Befehle bleiben im Commandkatalog begründet ausgewiesen und werden nicht als aufrufbare MCP-Einzelwerkzeuge veröffentlicht.

| Vorhandener Bereich | Verbindliche Registryabdeckung |
| --- | --- |
| Threads, Organisation, Notizen, Dateireferenzen | `thread_manage`, bestehende Threadtools |
| Snapshots und gespeicherte Prompts | bestehende Snapshottools, neu `prompts.list` |
| Whiteboards, Beiträge, Arbeitsstand | `whiteboard.*`, zwölf neue Lifecycle-/Lesebefehle |
| Knowledge, Graph, Beziehungen und Ereignisse | `knowledge_manage`, `graph.*` |
| Ansichten und belegte UI-Zustellung | `graph_view.*` |
| Dateiaktivität, Bibliothek, Import/Indexsuche | `activity.*`, `library.*`, bestehende Librarytools |
| Papierkorb, Konflikte, Wiederherstellung, Purge | `trash.*` |
| Akteure, Module und deklarative Modulfunktionen | `actors.*`, `modules.*`, dynamische `module.*` |
| Gate, Übergaben, Rückgaben und Fragen | bestehende Fachadapter, `gate.*` |
| Räume und Serversynchronisierung | `room.*`, `server_sync.*` mit bisherigen Freigaben |
| Profile, Backup, Restore, Migration und Export | `profiles.*`, `backup.*`, `migration.*`, `export.*` |
| Hausmeister | `hausmeister.*` |
| Authority-Ereignisse einlesen | neu `authority.import`, inerte Projektion über vorhandenen Validator |
| Ownerkontextsuche | `search.*`, weiterhin ausschließlich lokal/CLI |

Workshop-Neuentwicklung bleibt gemäß bestehendem Gesamtplan gestrichen. Sprache, Register und Transporthandshakes sind keine eigenständigen Fachaktionen. Neue Funktionen werden über quellverantwortete CommandSpecs registriert; Pythonmethoden werden nicht ungeprüft exportiert. Neue deklarative Modulbefehle und geänderte Freigaben erscheinen ohne Serverneustart. Neue eingebaute Quellfunktionen benötigen den aktualisierten ThreadDesk-Programmstand.

Die vollständige Discovery enthält einschließlich kompatibler Legacytools 172 JSON- beziehungsweise 175 SQLite-Werkzeuge. Nach Erhalt eigener Schema-Ressourcen liegt die gemessene Größe mit 323894/329626 Bytes unter dem aktuell konfigurierten Gegenstellenlimit von 524288 Bytes. [MCP-Vertrag](../../contracts/mcp-dynamic-v1.md) und [Whiteboardvertrag](../../contracts/whiteboards-v1.md) beschreiben Schemas, Namensgrenzen, Rechte, Belege und fachliche Grenzen.

Whiteboard und zugehöriger Thread teilen Titel, Archiv und Papierkorb. `whiteboard.delete` verlangt ausdrücklich `confirm_thread_move=true`; Originaldateien bleiben erhalten. Endgültiges Löschen erfordert weiterhin die konkrete Vorschau, Ampel/Blocker, Generation, Referenzdigest und exakte Löschbestätigung. Open/Closed ist gespeicherter Fachzustand mit UI-Pfad, keine Behauptung eines geöffneten Betriebssystemfensters. Bearbeitung hängt Korrekturen an; das ursprüngliche Log bleibt erhalten.

## Nachweise

- 68 gezielte MCP-/Command-/Modul-/Paketprüfungen bestanden; nach letzter defensiver Schemakopie nochmals alle 14 Dynamic-Cases bestanden.
- Erweiterungsrepro nach dem ersten Commit: lokale Schema-Referenzen waren unter `arguments` an die falsche Wurzel gebunden. Der enge Folgefix erhält eine eigene Fachressource und native Feldreferenzen. 84 Dynamic-/Command-/Modultests bestanden, einschließlich 26 zusätzlicher JSON-/SQLite-Fälle für `$defs`, Anker, Rekursion, vorhandene IDs, native Feldschemas und gesperrte externe Abfragen. Der überholte erste CI-Lauf wurde gestoppt; nur der aktualisierte Pin kann finale Freigabe erhalten.
- Die erste vollständige CI auf `5f38c8d` führte 2.518 Fälle aus: 2.513 bestanden, fünf fehlgeschlagen, keine übersprungen. [Fehlerbeleg](ci-failure-summary.json): eine veraltete Charakterisierung erwartete ausschließlich die feste MCP-Liste; vier Fälle betrafen neue Whiteboard-Übersetzungen und deren Wächter. Die Korrektur erhält die exakte Legacy-Prüfung und ergänzt dynamische Registry-/Löschbindings sowie vollständige Zustandslabel-Abdeckung. Der enge i18n-/Whiteboardlauf bestand mit 154 Fällen, Charakterisierung plus Dynamic-Cases mit 48 Fällen; beide Änderungen sind unabhängig freigegeben. Der fehlgeschlagene Gesamtlauf wird dadurch nicht nachträglich als grün behandelt; für den korrigierten Pin ist die reguläre zweifache Gesamt-CI erneut erforderlich.
- 112 gezielte Whiteboard-/KnowledgeGraph-/GraphChanges-/Reconciliationprüfungen einschließlich echter Browserabnahme bestanden. Nach letzter Metadatenhärtung nochmals 15 Lifecyclefälle bestanden. Der Browser belegt Korrektur mit Originalerhalt, Close/Open, Konfliktentwurf sowie Liveänderungen nach Rename/Archive/Delete/Restore. [Graphbild](whiteboard-live-graph.png), [Boardliste](whiteboards-list.png).
- Unabhängige Prüfinstanz: 51 vorhandene Regressionstests sowie 22 neue Dynamic-/Prompt-/Authority-/Paketfälle bestanden. Die Mengen überschneiden sich mit den obigen Läufen und werden nicht addiert.
- [source-checks.json](source-checks.json): echter separater stdio-Server für JSON und SQLite. Je 35 Ergebnisdigests kanonisch nachgerechnet; vollständiger Whiteboard-Lifecycle, Replay, Operations-/Revisionskonflikt, Graphzustände, Verbergen im Papierkorb, Wiederherstellung gleicher IDs und abgewiesenes Purge ohne Freigabe.
- `scripts/check_mcp_whiteboards.py` führt denselben Nachweis mit `--server /Applications/ThreadDesk.app/Contents/Resources/bin/ThreadDeskServer` direkt am fertigen Paket aus. Dabei werden `PYTHONPATH`/`PYTHONHOME` entfernt. Beide Paketentrypoints unterstützen dafür `--mcp` ohne Fenster- oder Listenerstart.
- JavaScript-Syntax und `git diff --check` bestanden. Pflicht-CI, Mergepin und finale Paketinstallation sind getrennte Integrationsschritte; lokale Tests ersetzen sie nicht. Deren tatsächliche Resultate gehören zum finalen Integrationsbeleg und PR-Verlauf.

## Gegenstelle und ausdrückliche Grenze

[counterpart.json](counterpart.json) dokumentiert die tatsächlich verbundene KiraBridge `0.8.0rc19`, Principal `chatgpt`, Modus `authorized_tools` und 34 entdeckte Tools. Ihre bestehende Konfiguration verwendet weiterhin den separaten ThreadDesk-Snapshot `770bbc9`. Der neue Quellstand wird dort durch einen ThreadDesk-Commit oder die Desktopinstallation nicht automatisch ausgewählt. Die Live-Abfrage belegt diesen Unterschied, keine erfolgreiche Ausführung der neuen Werkzeuge durch KiraBridge.

KiraBridge-Code, App, Konfiguration und Terminalsteuerung werden in diesem Auftrag nicht verändert. Die Auswahl des neuen ThreadDesk-Endpunkts und ein Aufruf aus dem tatsächlichen Zielprincipal bleiben deshalb eine konkret benannte externe Integrationsabhängigkeit. Eine alte 64-Tool-Grenze aus dem historischen Audit wird ohne Prüfung der laufenden Gegenstelle weder als aktueller Fehler noch als behoben behauptet. ThreadDesk liefert den eigenständigen MCP-Endpunkt, präzise Schemas und nachprüfbare Ergebnisse; Consumer-Caches und fremde Autorisierungsregeln kann es nicht selbst ändern.
