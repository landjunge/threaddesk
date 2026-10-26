# TD-20261026-ARCH: Architekturprüfung und Modulplan

Status: Prüfung abgeschlossen; vorgeschlagene Reparaturen nicht implementiert.
Geprüftes Repository: `/Users/landjunge/threaddesk-worktrees/codex2-file-receiver-20261024`, Commit `07e10bf`.
Keine Repository-Dateien oder Produktivdaten verändert. Quellen: Projektregeln `/Users/landjunge/threaddesk/AGENTS.md` und Workflow `/Users/landjunge/.threaddesk/Workflow/Workflow-Planerstellung-fuer-andere-KIs.md` gelesen.

## Bestätigte Befunde

### ARCH-F01: Events vor erfolgreichem Transaktionsabschluss

`api/service.py:57–66` speichert einen Thread und publiziert `thread.created` und `thread.switched`. `services/thread_management.py:102–117` ruft dies innerhalb einer Transaktion auf und kann danach beim Organisieren scheitern. `core/events.py:16–21` publiziert unmittelbar an Listener.

Isolierte Reproduktion mit JSON und SQLite und Python 3.12, temporäre Workspaces:

```sh
cd /Users/landjunge/threaddesk-worktrees/codex2-file-receiver-20261024
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3.12 /tmp/threaddesk-team-20261026/repro-rollback-events.py
```

Beobachtete Ausgabe (bereits vor diesem Bericht ausgeführt):

```text
JsonStore not_found persisted_threads= 0 events= ['thread.created', 'thread.switched']
SQLiteStore not_found persisted_threads= 0 events= ['thread.created', 'thread.switched']
```

Datenrollback funktioniert; Listener erfahren dennoch von nie persistierten Threads. Reparatur: Events innerhalb der Unit of Work sammeln, nach Commit zustellen, bei Rollback verwerfen. EventBus nicht pauschal ersetzen.

### ARCH-F02: Unterschiedlicher Änderungsvertrag je Transport

`ui/server.py:992–1025` nimmt bei Beschreibung, Status und Umbenennung keine Formularrevision oder Operationskennung entgegen und lädt vor Änderung den aktuellen Datensatz. `services/thread_management.py:97–139` prüft dagegen explizite `expected_revision` und bietet dauerhafte Idempotenz. CLI schreibt ebenfalls direkt über ThreadService, etwa `ui/cli.py:150–225`.

Die Storage-Revision selbst funktioniert: `storage/json_store.py:501–512`, `storage/sqlite_store.py:134–143`. Konkrete Lücke: Die vom Browser angezeigte Ausgangsrevision wird beim Absenden nicht mitgesendet; ein veraltetes Formular kann neuere Werte still ersetzen. Wiederholtes Absenden hat keinen dauerhaften Operationsbeleg. Architektur-/Codebefund, kein Browser-Reproduktionstest in diesem Auftrag.

### ARCH-F03: Transportabhängiger Fehlervertrag

HTTP `ui/server.py:311–316` reduziert Fehler auf Klassenname/Detail und HTTP 400/404; `ManagementError.code/details` gehen verloren. MCP `services/mcp.py:306–311` erhält sie für ManagementError. Konflikte können dadurch transportabhängig behandelt werden.

### ARCH-F04: Breite Fassaden, gezielte Rückabhängigkeiten

Dateigrößen: `ui/server.py` 1143 Zeilen; `ui/cli.py` 820; `api/service.py` 771; `services/library_import.py` 756. Größe allein ist kein Fehler; die fachliche Bündelung und mehrfachen Eintrittspfade erschweren konsistente Verträge. Keine Doppeldefinitionen in den vier Hauptfassaden gefunden.

AST-Prüfung: keine Imports aus `core`/`storage` in höhere Schichten. Rückimports: `services/library_import.py:308,595` importiert `api.service.ThreadService` nur zum Thread-Lesen, ersetzbar durch ThreadReader/ThreadStore; `services/mcp.py:7` importiert die API-Fassade und sollte klar als Adapter behandelt werden.

### ARCH-F05: Modulmechanik vorhanden

`services/modules.py` bietet Manifest, Fähigkeiten, Scopes, Freigaben, Aktivierungsstatus und isolierte Laufzeit. `ModuleRuntime.run:276–291` ist derzeit auf deklarierte Schreibaktionen zugeschnitten. Allgemeine Befehlsregistrierung muss Leseoperationen und explizite CommandSpecs ergänzen. Keine zweite Modulverwaltung aufbauen.

### ARCH-F06: CI und Laufzeitgrenzen

`.github/workflows/tests.yml:50–90` verwendet Python 3.12, Browserprüfung und zweimal die Gesamtsuite; ausgelassene Abnahmetests sind verboten. Native Windows-Prüfung ist ausdrücklich nach Nutzerbeschluss pausiert. Merge-Gates beibehalten. `pyproject.toml` nennt Python >=3.9; alle unterstützten Versionen wurden hier nicht getestet. Lokales `python3` ist 3.8.0 und ungeeignet; `python3.12` ist vorhanden und wurde zur Reproduktion benutzt.

## Zielarchitektur

`core`: Modelle, Fehler, gemeinsame Verträge; `services`: Fachlogik/Anwendungsbefehle; `storage`: JSON-/SQLite-Implementierungen; `api`: kompatible Fassade und zentrale Registrierung; MCP/CLI/HTTP/UI: dünne Adapter. `server_sync` bleibt eigener Fachbereich. KiraBridge konsumiert einen freigegebenen Katalog und dupliziert keine ThreadDesk-Fachlogik.

Vollständigkeit bedeutet: Fachfunktionen vollständig inventarisieren, ausdrücklich registrieren oder begründet ausschließen. Dynamik bedeutet keine freie Reflexion beliebiger importierbarer Methoden.

## Ausführbare Arbeitspakete

Alle Pakete vorgeschlagen, nicht implementiert. Standardgewicht je Paket 1. Fortschritt nur durch bestandene Abschlusskriterien.

| ID | Zuständigkeit / Dateibereich | Inhalt und Abschlusskriterium |
|---|---|---|
| ARCH-A01 | Backend: neue Verträge/Registry unter api oder services, bestehendes services/mcp.py | Explizite CommandSpec: Name/Aliasse, Modul, Schema-/Befehlsversion, Input-/Output-Schema, Handler, Wirkung, benötigte Scopes/Freigaben, Verfügbarkeit. Bestehende MCP-Namen erhalten. Abnahme: vollständige Metadaten; doppelte Namen/inkompatible Specs scheitern eindeutig; keine freie Reflexion. |
| ARCH-A02 | Backend: Dispatcher, core/errors.py, Transportadapter; nach A01 | Gemeinsame Validierung, Policy, Revision, Operationsbeleg, Fachaufruf und Ergebnis. thread_management weiterverwenden. Gleiche Fehlercodes für validation_error, not_found, revision_conflict, operation_conflict, Policy und Verfügbarkeit. Abnahme: äquivalente MCP-/HTTP-/CLI-Aufrufe liefern gleiche Fachresultate und Fehlercodes. |
| ARCH-A03 | Storage/Backend: core/events.py, api/service.py, services/thread_management.py, UoW; parallel A01 | Ereignisse an Commit koppeln. Abnahme: Fehlerreproduktion liefert bei beiden Backends keine Listenerereignisse; erfolgreicher Commit genau erwartete Ereignisse; wiederholte Operationskennung keine zweite Zustellung. |
| ARCH-A04 | UI/CLI: ui/server.py, Templates/Formulare, ui/cli.py; nach A02 | Formularrevision und stabile operation_id, gemeinsame Verwaltungsbefehle. Konfliktanzeige erhält Eingabe. Abnahme: zwei veraltete Browserstände überschreiben sich nicht still; Wiederholung dupliziert nichts; Archivierung/aktuelle Auswahl bleiben korrekt. |
| ARCH-A05 | Backend/UI: api/service.py, services/library_import.py, UI-Router; nach A02 | Fassade schrittweise nach Threads, Graph, Actors, Whiteboard, Handoffs und Library delegieren; bestehende Fachservices nutzen; ThreadService zunächst kompatibel halten. Library-Rückimporte entfernen. Abnahme: bestehende Schnittstellen kompatibel, keine neuen services→api/ui-Imports im Fachkern, passende Regressionstests je Extraktion. |
| ARCH-A06 | Integration: services/modules.py, Registry/Katalog, KiraBridge-Verbraucher; nach A01/A02 | Bestehende ModuleManifest-/Registry-Struktur um CommandSpecs und Kompatibilität ergänzen. Nur aktivierte/genehmigte/kompatible Specs veröffentlichen, Sperrgründe ausgeben. Abnahme: Aktivierung, Deaktivierung und Rechteentzug ändern Katalog deterministisch; gecachte Calls werden erneut geprüft. |
| ARCH-A07 | Test/Review: gezielte Vertragstests und CI; nach jeweiligem Paket | Abdeckung Services↔MCP/HTTP/CLI dokumentieren; Ausschlüsse begründen. JSON/SQLite, Schema/Handler, Policy, Konflikt, Wiederholung und Rollback prüfen; Importregel gegen neue Rückabhängigkeiten. Abnahme: kein registrierter Befehl ohne Handler/Schema; jede öffentliche Fachfunktion eingeordnet; alle erforderlichen CI-Gates bestanden. |

## Geprüft und offen

Geprüft: statische Schichtimporte; Fassadengrößen und Doppeldefinitionen; Änderungen-/Fehlerpfade; vorhandene Modulverwaltung; CI-Konfiguration; isolierte Event-Rollback-Reproduktion JSON+SQLite.
Offen: Browser-Reproduktion veralteter Formulare; komplette Fachfunktionsabdeckung (anderer Teamauftrag); produktive KiraBridge-Aktivierung (Koordinator); Umsetzung und zugehörige Regressionstests. Keine Vollsuite in diesem Auftrag ausgeführt.
