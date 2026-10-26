# ThreadDesk und KiraBridge gemeinsam vervollständigen

**Historischer Diagnose- und Planstand.** Der anschließende Nutzerauftrag beschränkt alle weiteren Bau- und Planpakete auf ThreadDesk. Maßgeblich ist jetzt der [konkrete ThreadDesk-Plan](THREADDESK-GRAPH-PAPIERKORB-BEDIENUNG-20261026.md). Die unten genannten KiraBridge-Implementierungspakete sind damit nicht Teil des aktuellen Auftrags; sie bleiben als historische Analyse erhalten.

Stand: 26. Oktober 2026. Planungsbasis ThreadDesk `07e10bf10ad24084becb8ae24e869a624f0b16d1`.

ThreadDesk soll seine fachlichen Funktionen über einen vollständigen, versionierten Katalog für KiraBridge anbieten. Lesen, Schreiben und Betriebsaktionen erhalten klar getrennte Verträge. Bestehende Fachservices, Speicherprotokolle und die KiraBridge-Queue bleiben die Grundlage. Zuerst werden die reproduzierten Konsistenzfehler behoben; anschließend wächst die Abdeckung in kleinen Modulpaketen.

Dieser Auftrag erstellt den Abgleich, die Diagnose und den detaillierten Umsetzungsplan. Die unten aufgeführten Reparaturen und Erweiterungen sind noch nicht implementiert. Eine aktivierte oder aktualisierte Produktionsinstallation folgt daraus nicht.

## 1. Abgleich und erhaltene Arbeitsstände

| Gegenstand | Beobachteter Stand | Ergebnis des Abgleichs |
| --- | --- | --- |
| GitHub ThreadDesk `origin/main` | `07e10bf`, nach frischem Fetch | Grundlage der Prüfung |
| Lokaler ThreadDesk `main` | vorher `3fcadb6`, 107 Commits hinter GitHub | Im vorhandenen sauberen Worktree ausschließlich vorgespult auf `07e10bf` |
| Aktueller Arbeitsort | `/Users/landjunge/threaddesk-worktrees/codex2-file-receiver-20261024` | Für aktuellen Quellstand und diesen Plan weiterverwenden |
| Älterer Hauptordner | `/Users/landjunge/threaddesk`, Branch `feat/unified-cleanup`, `65aafdf` | Unverändert erhalten; 27 branchspezifische Commits gegenüber aktuellem `main`, gestagte, ungestagte und unversionierte Änderungen |
| KiraBridge `origin/main` | `7e3b8a3`, nach frischem Fetch | Separate Codebasis; keine fremden Entwicklungsbranches zusammengeführt |
| Geprüfte KiraBridge-Adapterquelle | vorhandener Worktree `library-receive-20261024`, `d2edeb6` | Codebefunde und Tests beziehen sich ausdrücklich auf diesen Stand |
| KiraBridge Betrieb | Gemeinsamer Arbeitsspeicher nennt inzwischen RC17 `14468ad` und weitere parallele Arbeiten | Historische Reparaturdokumentation nicht als aktuellen Betriebsstand ausgeben; keine dieser Arbeiten überschreiben |

Die Sicherung liegt lokal unter `/Users/landjunge/ThreadDesk-Backups/sync-plan-20261026T165337Z`. Sie enthält ein geprüftes Git-Bundle aller damaligen Referenzen, getrennte Binärpatches für Index und Arbeitskopie, ein Archiv der 26 betroffenen lokalen Dateien, Status und Worktreeliste sowie SHA-256-Werte. Zusätzlich existiert der Branch `backup/pre-sync-plan-20261026T165337Z`.

Wiederherstellung: Bundle zuerst mit `git bundle verify` prüfen, daraus einen getrennten Wiederherstellungs-Worktree erzeugen, anschließend `staged.patch` mit `git apply --index`, `unstaged.patch` mit `git apply` und das Dateiartefakt nach Einzelprüfung einspielen. Der alte Ordner selbst wurde nicht verändert und bleibt unmittelbar verwendbar. Verschachtelte Worktrees, ignorierte Dateien, Umgebungen, aktive Anwendungen und konfigurierte Startpfade wurden erhalten. Die Sicherung enthält lokale Inhalte und wird nicht ins Repository hochgeladen.

Der aktuelle lokale `main` und GitHub-`main` sind damit abgeglichen. Der ältere Hauptordner bleibt ein ausdrücklich separater Entwicklungsstand; er ist keine zweite aktuelle `main`-Arbeitskopie. Dieser Plan wird auf einem eigenen Dokumentationsbranch committed und gepusht. Nicht zusammengeführte historische Branches werden dadurch weder freigegeben noch automatisch integriert.

## 2. Befunde und Reparaturpriorität

### F01 Neuere Notizen werden durch veraltete UI-Eingaben überschrieben

**Priorität P1, reproduziert mit JSON und SQLite.** Zwei Clients lesen Revision 2. Client A speichert eine neue Notiz und erhält HTTP 200, Revision 3. Client B sendet seine ältere Eingabe und erhält ebenfalls HTTP 200, Revision 4; der Inhalt von A ist verloren.

`ui/server.py:776–784` akzeptiert beim Notizspeichern keine erwartete Revision oder Operationskennung. `api/service.py:327–335` liest unmittelbar vor dem Ersetzen den aktuellen Datensatz. Der Storage selbst prüft Revisionen korrekt; ihm wird hier die veraltete Browserrevision nicht mitgeteilt. Beschreibung, Status und Umbenennen besitzen entsprechende Vertragslücken (`ui/server.py:992–1025`). Der vorhandene MCP-Verwaltungsweg prüft dagegen `expected_revision` und `operation_id` in `services/thread_management.py:97–139`.

**Reparatur:** UI und CLI an denselben fachlichen Änderungsvertrag anbinden. Formular enthält die angezeigte Revision und eine stabile Operationskennung. Veralteter Stand ergibt `revision_conflict`/HTTP 409; Entwurf bleibt erhalten. Nicht automatisch mit frischer Revision erneut überschreiben.

**Abnahme:** Zwei Browser, beide Speicherarten, vollständiger Erhalt des zuerst gespeicherten Inhalts, sichtbarer Konflikt im zweiten Browser, Entwurf weiterhin vorhanden; identische Wiederholung derselben Operation ohne zweite Änderung; gleiche ID mit anderem Inhalt ergibt `operation_conflict`.

### F02 Rückgerollte Erstellung veröffentlicht bereits Erfolgsevents

**Priorität P1, reproduziert mit JSON und SQLite.** `manage(create, parent_thread_id="missing")` endet mit `not_found`; gespeichert bleiben null Threads. Trotzdem erhalten Listener `thread.created` und `thread.switched`.

`api/service.py:57–66` emittiert beim Anlegen unmittelbar. Dieser Aufruf befindet sich innerhalb der Transaktion von `services/thread_management.py:102–117`. `core/events.py:16–21` kennt deren Commit nicht.

**Reparatur:** Fachereignisse innerhalb der bestehenden Transaktionsgrenze sammeln, nach erfolgreichem Commit publizieren und bei Rollback verwerfen. Keine zweite Persistenzlogik im EventBus einführen. Für externe dauerhafte Zustellung gesondert entscheiden, ob ein transaktionales Outbox-Artefakt erforderlich ist; ein speicherinterner Bus garantiert keine Zustellung nach Prozessabsturz.

**Abnahme:** Der Fehlerfall publiziert keine Events; erfolgreicher Commit liefert die erwarteten Events genau einmal; idempotente Wiederholung liefert keine neuen Events. Listenerfehler nach Commit dürfen keinen scheinbaren Datenrollback erzeugen.

### F03 Dynamischer Live-Katalog ist deaktiviert

**Priorität P1 für Integration, aktueller Live-Befund:** `threaddesk_dynamic_catalog({})` liefert `{"tools": [], "enabled": false}`. Dies entspricht dem ausgeschalteten Opt-in und beweist keinen Verbindungs- oder Berechtigungsfehler. Der Code kehrt in diesem Fall vor diesen Prüfungen zurück.

Vor Aktivierung sind das tatsächlich geladene Profil, der ThreadDesk-Source-Pin, Workspace, Speichertyp, Version und die vorhandene Berechtigung zu prüfen. `dynamic_read_proxy=true` allein behebt keine fehlenden Fachfunktionen und aktualisiert keine Installation. Details zum vorhandenen Opt-in stehen in KiraBridge `docs/DYNAMIC-THREADDESK-PROXY.md`.

### F04 Fachfunktionen fehlen im maschinellen Katalog

**Priorität P1, Codebefund:** ThreadDesk besitzt 34 MCP-Tools; 12 sind explizit als lesend annotiert. Die Weboberfläche hat 62 Routen. Routen und Funktionen sind unterschiedliche Zähleinheiten; daraus wird keine prozentuale Funktionsabdeckung berechnet.

Whiteboard-Liste, Anhängen und Arbeitsstand existieren in `api/service.py:542,546,558` und `ui/server.py:565,574,586`, fehlen jedoch im MCP-Katalog. Weitere Lücken betreffen Graph, Akteure, lokale Suche, Datenprofile, Backup/Restore, Migration, Hausmeister und Raum-Sync. Die vorhandenen KiraBridge-Reads stellen keinen alternativen Whiteboardzugang bereit.

Die dynamisch zulässigen Reads sind aktuell: `library_receive_status`, `library_search`, `library_file_info`, `get_reentry`, `get_issued_handoff`, `thread_operation_status`, `list_threads`, `get_thread`, `current_thread`, `list_snapshots`, `list_gnom_jobs`, `check_gate`. Daneben existieren statisch sechs Queue-Reads, zehn Thread-Verwaltungsaktionen, vier Knowledge-Aktionen und weitere Fachwege für Handoffs und Returns. Diese Liste wird nicht als vollständige dynamische Schreibschnittstelle ausgegeben.

### F05 Änderungen dynamischer Tools fehlen im Discovery-Fingerabdruck

**Priorität P1 für verlässliche Dynamik, Codebefund:** KiraBridge `mcp_gateway/proxy.py:37–43` berechnet den Fingerabdruck aus Basiswerkzeugen. Dynamische `td_`-Tools kommen erst in `:132–145` hinzu. Ein erneutes Listing sieht Änderungen, eine Änderung allein dieser Tools erhöht `change_generation` aber nicht.

**Abnahme:** Neue, entfernte und schema-veränderte ThreadDesk-Funktionen sowie Rechteentzug ändern die Revision des tatsächlich veröffentlichten Gesamtkatalogs. Verbundene Clients erhalten eine echte Änderungsmitteilung oder einen ausdrücklich dokumentierten Reconnect-/Refreshpfad. Keine spontane Aufweckung inaktiver Chats versprechen.

### F06 Kataloggrenze und Operationskennung passen noch nicht zu voller Abdeckung

**Priorität P2, isoliert reproduziert:** KiraBridge `_fresh_tools()` lehnt mehr als 64 Peer-Tools insgesamt ab. Bereits ein Read plus 64 Writes ergibt `threaddesk_tool_limit`, obwohl nur ein Read freigegeben würde (`threaddesk_dynamic.py:67`). Künftige Vollständigkeit braucht Pagination und eine Grenze pro Seite/Ergebnis sowie eine definierte Gesamtobergrenze; keinen unbegrenzt großen Katalog.

Die statische Queue bindet Operationskennungen an Principal und Workspace (`threaddesk_manager.py:97–117`); der dynamische Operationslookup reicht Kennungen unverändert weiter (`threaddesk_dynamic.py:111`). Das ist eine unterschiedliche ID-Semantik, kein belegter Rechtebruch. Öffentliche logische Operationskennung und interne Speicherkennung müssen im neuen Vertrag eindeutig zugeordnet sein.

### F07 Fehler und Modulgrenzen sind uneinheitlich

**Priorität P2, Codebefund:** HTTP reduziert Fehler auf Klassenname/Detail und 400/404 (`ui/server.py:311–316`); der Management-MCP-Weg erhält Fachcode und Details (`services/mcp.py:306–311`). Konflikte müssen transportübergreifend denselben Fachcode und passende HTTP-Statuswerte liefern.

Die vorhandenen Layer funktionieren grundsätzlich: keine geprüften Rückimporte aus `core`/`storage` in höhere Schichten. Die Fassade `api/service.py` bündelt jedoch viele Domänen; UI und CLI enthalten parallele Zuordnungen. `services/library_import.py:308,595` importiert für Thread-Lesen die API-Fassade. Dafür bestehen bereits Speicherprotokolle. Dateien werden entlang fachlicher Zuständigkeiten aufgeteilt; Zeilenzahl allein ist kein Reparaturgrund.

## 3. Was vollständig und dynamisch bedeutet

Jede fachliche Funktion erhält genau einen stabilen Eintrag im Sollinventar. Jeder Eintrag besitzt einen Verantwortlichen, Eingabe-/Ausgabevertrag, Wirkung, benötigten Scope, unterstützte Backend-/Vertragsversionen und eine begründete Verfügbarkeit. Reine Darstellung wie Browserzoom ist kein zusätzlicher Fachbefehl.

Ein Status unterscheidet `available`, `disabled`, `permission_required`, `unsupported_version`, `unavailable` und `local_ui_only`. Der letzte Status benötigt eine konkrete Begründung. Ein berechtigter Benutzer kann so erkennen, ob eine Funktion fehlt, deaktiviert ist oder in seinem Profil nicht ausgeführt werden darf. Der Diagnosekatalog selbst wird nach Berechtigungen gefiltert und verrät keine fremden Objektinhalte.

**Dynamik:** Ein fachlich registrierter und freigegebener neuer Befehl erscheint nach Discovery ohne neue KiraBridge-Allowlist oder Spezialimplementierung pro Befehl. Das setzt einen vorher implementierten kompatiblen generischen Vertrag voraus. Ein unbekannter neuer Wirkungstyp oder inkompatibles Schema darf ein Bridge-Update erfordern.

**Vollständigkeitsmaß:** zugeordnete fachliche Funktionen / alle inventarisierten fachlichen Funktionen. Davon getrennt: tatsächlich verfügbare Funktionen für ein konkretes Profil und erfolgreich abgenommene Funktionen pro Backend. Keine 100-Prozent-Aussage aus bloß registrierten Methodennamen.

## 4. Funktionsmatrix als verbindlicher Ausbauumfang

Diese Domänenmatrix ist das Startinventar. Paket P01 ersetzt sie durch eine zeilenweise maschinenlesbare Liste der konkreten Befehle und ihrer vorhandenen Adapter.

| Modul | Bestehende Grundlage | Nächste Katalog-/Vertragsarbeit | Abnahme und Grenzen |
| --- | --- | --- | --- |
| Threads und Kontext | `thread_management`, `ThreadService`, Revisionen/Operationsbelege | Erstellen, Lesen, Suchen, Aktualisieren, Organisieren, Notizen, Dateien, Archiv, Löschen, Wechseln vereinheitlichen | Revisionskonflikte, Replay, Elternzyklen, aktive Auswahl, JSON/SQLite |
| Snapshots und Wiedereinstieg | Snapshotdienste, `get_reentry`, Listen | Erstellen/Lesen/Laden klar als getrennte Befehle | Laden ist Write; Kontext/aktive Auswahl und Revision erhalten |
| Whiteboard | `whiteboard`, `whiteboard_merge`, Arbeitsstand | Lesen, paginiertes Listing, Stand, Append mit Akteur/Task/Operation | Historie append-only; Duplikat-/Konfliktprüfung; vollständiger Readback |
| Akteure und Module | `actors`, `modules` | Akteurs-/Instanzzuordnung, Manifestliste, Aktivierungsstatus; Änderungen gesondert | Angegebene `actor_id` ist kein Identitätsbeweis; neue Modulrechte nicht automatisch gewähren |
| Wissen und Graph | `knowledge*`, `graph`, vorhandene Knowledge-MCP-Wege | Knoten/Relationen lesen und ändern, Review, nachvollziehbare Exporte | Referenzen, Herkunft, Revisionen und Transaktionsgrenzen prüfen |
| Suche | `services/search`, `storage/search_*` | Lokale Thread-/Wissens-/Dateisuche mit Filtern und Pagination | Fehler nicht als leeres Suchergebnis kaschieren; kein Schreibeffekt bei Reads |
| Bibliothek und Dateien | `library_import`, `library_receive`, `library_backup`, vorhandener KB-Dateiadapter | Listen, Suche, Metadaten, Import/Empfang/Export/Checkpoint | Bestehenden Receiver verwenden; eindeutige Quelle/Zielbindung und Readback, kein alter Queueauftrag erneut |
| Handoffs und Rückgaben | `issued_handoffs`, `return_inbox`, `gnom_*`, bestehende Bridge-Wege | Lesen, Erstellen, Eingang, Annahme/Ablehnung, Status | ThreadDesk speichert Aufträge; externe Ausführung bleibt KiraBridge/Agent zuständig |
| Profile, Backup und Migration | `workspace_backup`, `portable_backup`, `migration/*`, JSON/SQLite-Migration | Prüfen/Planen/Exportieren getrennt von Restore/Migrate/Profilwechsel | Backupmanifest, Integrität, atomarer Wechsel, Datenerhalt und konkret geprüfter Rollback |
| Räume und Server-Sync | `room_sync`, eigener Bereich `server_sync` | Raum-/Geräte-/Syncstatus, kontrollierte Verbindungs- und Transferaktionen | Bestehende Verträge behalten; Personen-/Geräteidentität unterscheiden; kein Netzwerkeffekt als Read |
| Hausmeister und Einstellungen | `hausmeister`, `ollama_local`, `desktop_runtime` | Status/Modelle lesen; Konfiguration/Start/Stop als eigene Betriebsaktionen | Vorhandene Laufzeitgrenzen; kein Shell-/Agentenausführen aus ThreadDesk-Kern |
| Vorschauen und Export | Prompt-, Paket-, visuelle Exportdienste | Reine Vorschau von Speichern/Dateiexport trennen | Nur nach tatsächlichem Effekt als Read annotieren; sichere Ziel- und Größenbindung |

## 5. Zielarchitektur und Codequalität

Eine explizite Befehlsregistrierung verbindet vorhandene Domänen mit dünnen Transportadaptern. Keine automatische Freigabe aller Python-Methoden und kein zweiter Orchestrator.

```text
ThreadDesk UI / CLI / MCP
          |
     Command-Registry und Dispatcher
          |
     vorhandene Fachservices
          |
     Speicherprotokolle -> JSON / SQLite

KiraBridge MCP -> Discovery / Policy / bestehende Queue
                                  |
                         ThreadDesk MCP-Vertrag
```

### Gemeinsame CommandSpec

Vorgeschlagener Ort: `services/commands/` mit kleinen Dateien `models.py`, `registry.py`, `dispatch.py`, `errors.py`, `catalog.py` und domänenspezifischen Spezifikationen. Die API-Fassade delegiert zunächst dorthin; bestehende MCP-Namen bleiben kompatible Aliasse.

Eine Spezifikation enthält mindestens: `id`, `module_id`, Vertragsversion, Aliasse, fachlichen Handler, Input-/Output-Schema, Effektklasse, erforderliche Scopes, Objekt-/Workspacebindung, Anforderungen an Revision und Operationskennung, Backendunterstützung und Verfügbarkeitsprüfung. Metadaten und Handler gehören demselben Fachmodul. Handler erhalten keine FastAPI- oder MCP-Requestobjekte.

Effekte unterscheiden Lesen, lokale Mutation, Dateiimport/-export, Netzwerkwirkung, Wiederherstellung/Migration und Laufzeitsteuerung. Die Effektklasse hilft bei Prüfung und Darstellung; die tatsächliche Berechtigungsentscheidung erfolgt pro Aufruf. MCP-Annotationen allein ersetzen diese Entscheidung nicht.

### Module und bestehende Grenzen

`services/modules.py` besitzt bereits `ModuleManifest`, `ModuleRegistry`, Freigaben, Aktivierungsstatus und `ModuleContext`. Diese Mechanik um Command-IDs und Vertragskompatibilität erweitern. `ModuleRuntime.run` ist bisher auf Schreibaktionen ausgerichtet; Read-Ausführung ausdrücklich ergänzen. Keine konkurrierende zweite Modulverwaltung einführen.

`core` hält Modelle, Fehler und schlanke Verträge. `storage` implementiert die vorhandenen Protokolle. `services` enthält Fachlogik. `api` bleibt während der Umstellung kompatible Fassade. UI, CLI und MCP enthalten Eingabe-/Ausgabeanpassung und delegieren. `server_sync` bleibt eigener Fachbereich.

`library_import` erhält für Thread-Lesen die vorhandene Abstraktion `ThreadReader` beziehungsweise das `ThreadStore`-Protokoll statt API-Rückimport. Änderungen pro Domäne in kleinen Commits; keine fachfremde Gesamterneuerung. Vorhandene öffentliche Importpfade bleiben während einer dokumentierten Übergangsphase erhalten.

### Dynamik auf KiraBridge-Seite

Vorhandenen `threaddesk_manager` als Fassade und bestehende Queue/Policy verwenden. Bei wachsendem Umfang intern nach `catalog`, `schema`, `policy` und `invoke` aufteilen; kein neues Zugangsdatenlager, kein zweiter Scheduler. KiraBridge importiert keine ThreadDesk-Interna und schreibt nicht in dessen Datenbank.

Lesende Aufrufe bleiben im vorhandenen geprüften Direktpfad. Schreibende/Betriebsaufrufe verwenden einen neuen generischen Invoke-Vertrag über die bestehende Queue. Eine generische Erweiterung der Bridge ist erforderlich; danach benötigen kompatible neue Fachbefehle keinen neuen Bridge-Spezialhandler.

Jede Ausführung prüft aktuellen Katalog, Vertragsversion, Workspaceidentität, Capability, Principal, Scope, Argumente und Wirkung. Schreiboperationen benötigen stabile öffentliche Operationskennungen, erwartete fachliche Revision, atomaren Ergebnisbeleg und Statusabfrage. Eine unklare Antwort bedeutet `unknown`; Status zuerst abgleichen, kein blindes Replay. Fehlende oder entzogene Rechte sperren auch bereits gecachte Aliasse.

Katalog und Cache besitzen eine deterministische Revision über alle tatsächlich exportierten Tools, Versionen, Schemas und relevante Verfügbarkeiten. Änderungen werden über echte `tools/list_changed`-Zustellung beziehungsweise einen expliziten Refreshpfad sichtbar. Pagination und Größen-/Tiefengrenzen erhalten die Begrenzung; externe Schema-Referenzen werden nicht ungeprüft aufgelöst.

## 6. Ausführbare Arbeitspakete

Die Tabelle legt Reihenfolge, Zuständigkeit, Dateibereich und konkrete Abschlusskriterien fest. Jedes Paket erhält standardmäßig Gewicht 1. Fortschritt ist die Zahl abgenommener Pakete geteilt durch 15; Teilimplementierung ohne Abnahme zählt nicht als fertig. Die Analyse dieses Auftrags ist kein Umsetzungsfortschritt.

| ID / Priorität | Ziel und Dateibereich | Verantwortung / Abhängigkeit | Abschlusskriterium |
| --- | --- | --- | --- |
| P01 / P1 | Vollinventar in `docs/contracts` plus maschinenlesbarer Capabilitymatrix; 34 bestehende Tools, 62 Routen und CLI-/Serviceaktionen zuordnen | TD-Vertragsverantwortlicher; Start | Jede Fachaktion hat stabile ID, Modul, Adapter, Wirkung, Scope, Backend, Status und Testreferenz oder begründete Ausnahme |
| P02 / P1 | F01 beheben: Threadformulare, CLI, `thread_management`, gemeinsame Fehlerabbildung | TD-UI + Backend; unabhängig von großer Registry starten | Isolierter Stale-Edit-Repro schlägt danach mit 409 fehl; Entwurf bleibt; Replay und andere Nutzlast geprüft; JSON und SQLite |
| P03 / P1 | F02 beheben: Fachtransaktion und Commit-Events in API/Management/Eventgrenze | TD-Storage/Backend; parallel P02 | Fehlgeschlagene Erstellung sendet keine Erfolgsevents; Commit und identischer Replay liefern keine Doppelereignisse |
| P04 / P1 | `services/commands` und gemeinsamer Ergebnis-/Fehlervertrag, zuerst vorhandene Threadbefehle | TD-Backend; P01, Abstimmung mit P02/P03 | Keine doppelte Fachlogik; Schemas/Handler/Aliasse eindeutig; MCP/HTTP/CLI gleiche Fachfehler; alte MCP-Namen kompatibel |
| P05 / P1 | Bestehendes Modulmanifest um Commands/Kompatibilität erweitern | TD-Modulverantwortlicher; P04 | Installation aktiviert nichts automatisch; Aktivieren/Deaktivieren/Rechteentzug deterministisch im Katalog; Reads und Writes getrennt geprüft |
| P06 / P1 | Whiteboard und Akteursstatus lesend registrieren, danach Graph-/Suchreads | TD-Fachmodule; P04/P05 | Existierendes Whiteboard über frische MCP-/Bridge-Discovery erreichbar; Pagination, untrusted Inhalt, keine Read-Mutationen |
| P07 / P1 | Bridge-Discovery: Gesamtkatalogrevision, Refresh, Pagination, Diagnosestatus, Versions-/Workspacebindung | KB-Adapterverantwortlicher; P04, gemeinsam mit P06 | Synthetisches neues Readtool ohne Bridge-Quelländerung entdeckt; Entfernen/Schema-/Rechteänderung invalidiert Cache; 65-Toolfall definiert behoben |
| P08 / P1 | Generischer Queue-Invoke für Writes; Operationslookup normieren | KB-Queue + TD-Verträge; P04/P07 | Gleiche öffentliche Operations-ID in Submit/Lookup/Completion; Revision/Principal/Scope geprüft; Retry/Timeout/unknown/Replay gezielt abgenommen |
| P09 / P1 | Whiteboard-Append als erstes dynamisches Write | TD-Whiteboard + KB; P06/P08 | Vorhandene Historie unverändert; gleiche Operation einmal; Nutzlastkonflikt erkannt; unabhängiger Readback enthält den neuen Eintrag |
| P10 / P2 | Threads/Snapshots/Knowledge/Graph vollständig registrieren | TD-Domänen; P01/P04/P08 | Matrix der Domänen vollständig; jede Mutation konsistent und idempotent; vorhandene Revisionen und Herkunft bleiben erhalten |
| P11 / P2 | Library/Suche/Handoffs/Returns vervollständigen | TD- und KB-Fachadapter; P08/P10 | Bestehender Receiver wiederverwendet; Quelle/Ziel, Checkpoint, Return-Deduplizierung und Readback; keine Wiederholung historischer Jobs |
| P12 / P2 | Backup/Profile/Migration fachlich registrieren | TD-Datenverantwortlicher; P08, Backupverträge | Preview/Verify von Restore getrennt; vollständiger Datenerhalt im isolierten Workspace, Fehlerrollback und Neustart belegt |
| P13 / P2 | Rooms/Server-Sync/Hausmeister/Einstellungen/Vorschau und Exporte vervollständigen | Zuständige TD-Domänen; P08/P11/P12 | Jede Restfunktion zugeordnet; Netzwerk-/Datei-/Laufzeiteffekte ausdrücklich geprüft; unterstützte Backends/Versionen nachvollziehbar |
| P14 / P2 | Fassade und Adapter aufräumen, Importregeln und Vertragsdriftprüfung | TD-Architekturverantwortlicher; schrittweise ab P04, Abschluss nach P13 | Keine neuen Fachkern-Rückimporte; keine konkurrierenden Handler-/Allowlisten; dokumentierte Kompatibilität; alle Matrixzeilen ausführbar oder begründet ausgenommen |
| P15 / P1 für Freigabe | Integration, Pflicht-CI, Paket, isoliertes Profil, tatsächliche MCP-Clientabnahme | Koordinator + unabhängiger Reviewer; P02–P14 | Finale Pins, CI-Gates, konkrete Pakete und gestartete Versionen belegt; aktueller Read + ausdrücklich erlaubter Write + Readback + Offline-/Restartfall; danach konkrete Aktivierungs-/Installationsfreigabe anwenden |

Kritischer Pfad: P01 → P04 → P05/P06/P07 → P08 → P09 → Domänenvollständigkeit → P14/P15. P02 und P03 beginnen parallel dazu. Ein schneller erster Nutzen ist F01/F02 behoben plus lesbarer Whiteboardzugang; dies ist ein Teilmeilenstein und keine vollständige Integration.

## 7. Teamarbeit und Übergaben

Der Koordinator besitzt Inventar, Abhängigkeiten und Integrationsbranch. Ein Backend-/Storage-Auftrag bearbeitet Konsistenz und gemeinsame Commands; ein UI-/CLI-Auftrag die sichtbaren Änderungsverträge; ein Bridge-Auftrag Discovery/Policy/Queue. Nach Abschluss eines Bereichs prüft ein anderer Agent die konkreten Änderungen unabhängig. Gleichzeitige Bearbeitung derselben Datei vermeiden und bei gemeinsamem `thread_management` eine klare Eigentümerschaft festlegen.

Jeder Auftrag referenziert Planstand, `task_id`/`step_id`, Quellpin, Regeln, Workspace, Dateibereich, Grenzen, Abhängigkeiten und Abschlussbeleg. Übernahme und Session müssen bestätigt sein. Nach jedem erfüllten Punkt sofort ein Ping mit Ergebnis und Beleg, Blocker sofort. Spätestens nach 60 Sekunden ohne Rückmeldung Status nachfragen; ein echter Timer gehört zum Auftrag. Ein Timeout ist kein bewiesener Prozessfehler und startet keinen Ersatzagenten automatisch.

Maßgeblicher vorhandener Arbeitsspeicher bleibt „ThreadDesk und KiraBridge – Wechselentwicklung durch Codex“, Thread `188ce4729a62`. Keine konkurrierende Whiteboardinstanz erstellen. Ein Append benötigt beobachtete Revision und stabile Operation; danach unabhängig zurücklesen. Unsichere Schreibantworten zuerst über Operationsstatus abgleichen. Der derzeit fehlende native Whiteboard-MCP-Zugang wird in P06/P09 behoben; ein Dateilesen oder Kontextnotiz-Append wird nicht als bereits fertige neue Schnittstelle ausgegeben.

Der Analyseauftrag wurde tatsächlich im Team ausgeführt: `functional_audit`, `dynamic_bridge_audit` und `architecture_audit` mit bestätigter Übernahme. Ergebnisse und Reproduktionen liegen unter [Prüfbelege](../evidence/threaddesk-kirabridge-audit-20261026/README.md). Die lokale Timerprüfung wurde als eigener Prozess gestartet; ein erster abgekoppelter Start überlebte das Toolende nicht und wurde durch eine kontrollierte laufende Exec-Session ersetzt. Für spätere Bauaufträge ist das tatsächliche Fortleben des Timers vor Arbeitsbeginn zu prüfen.

## 8. Tests und Abschlussgates

Reproduktion und Vertragstests verwenden temporäres HOME und einen eigenen Workspace. Keine Nutzerdateien oder produktiven Queues als Testdaten verwenden. Es existieren passende Pythonumgebungen; das unqualifizierte `python3` auf diesem Rechner ist 3.8 und unterschreitet die Projektanforderung ≥3.9. Geprüfte Interpreter explizit verwenden und `PYTHONPATH` an den dokumentierten Quellpin binden.

In diesem Analyseauftrag bestanden 68 unterschiedliche ausgewählte ThreadDesk-Fälle einschließlich eines echten Chromium-Neustarttests sowie 55 KiraBridge-Vertragsfälle und eine ThreadDesk-Annotationsprüfung. Die zuerst unvollständige Python-Testumgebung und der zunächst fehlende Browserpfad wurden ausschließlich für betroffene Fälle korrigiert. Die vorhandene lokale `.venv` meldet zudem Distributionsmetadaten `0.1.0` bei Quellversion `0.1.2`; `serverInfo.version` allein belegt daher keinen aktuellen Source-Pin. Das unabhängige Planreview bestätigte die Architektur- und Ereignisabnahmen ohne blockierenden Widerspruch; es ist kein Review künftiger Implementierungen.

Pro Änderung nur betroffene Vertrags-/Regressionsfälle prüfen. Nach Fehlschlägen nur die betroffenen Fälle nachprüfen, Ursache und ersten Fehler erhalten. Die verpflichtende CI bleibt unverändert: `.github/workflows/tests.yml` verlangt einschließlich Browsern zweimal die Gesamtsuite und keine übersprungenen Abnahmetests. Ein lokaler Teilerfolg ersetzt diese Gates nicht. Native Windows-Entwicklung ist nach bestehendem Nutzerbeschluss pausiert und wird hier nicht neu gestartet.

Pflichtfälle für Commands: korrekte Eingabe, unbekannte Felder, Schema-/Versionskonflikt, fehlende/entzogene Berechtigung, falscher Workspace, veraltete Revision, identischer Replay, andere Nutzlast unter gleicher ID, Rollback ohne Events, Verbindungsabbruch mit unklarem Ergebnis. Reine Reads werden auf unbeabsichtigte Datei-/Datenänderungen geprüft. Speichervertragstests laufen auf JSON und SQLite, soweit das jeweilige Modul beide unterstützt.

Die reale Clientabnahme prüft tatsächliches `tools/list`, Gesamtkatalogrevision und Änderungssignal, einen Read, einen ausdrücklich erlaubten neuen Write samt Readback, Rechteentzug sowie Offline-/Reconnectverhalten. Gitstand, Paketversion und laufender Source-Pin werden getrennt festgehalten. UI-/Desktop-Smoke benötigt sichtbare Bedienprüfung. Keine allgemeine Funktionsfähigkeit aus erfolgreichen Unit-Tests ableiten.

Bei einer späteren produktiven Aktivierung werden vorher ein konkreter Konfigurationsdiff und ein geprüftes Paket bereitgestellt. Die bestehende Berechtigungsentscheidung gilt pro Operation; keine zusätzlichen Freigaben erfinden und keine erforderlichen übergehen. Bereits laufende andere KiraBridge-Entwicklungs-, Installations- und Releaseaufträge bleiben in ihrem eigenen Zuständigkeitsbereich.

## 9. Quellen und Einordnung

Projektregeln: `/Users/landjunge/threaddesk/AGENTS.md` und die lebende Referenz `/Users/landjunge/.threaddesk/Workflow/Workflow-Planerstellung-fuer-andere-KIs.md`. Bestehende Produktentscheidungen bleiben gültig: [Golden Rules](../usability/GOLDENRULES.MD), [Module und bisherige Teamplanung](../TEAMPLAN.md), [MCP](../MCP.md), [Dateiempfang](../contracts/library-receive-v1.md), [Bibliotheksbackup](../contracts/library-backup-v1.md), [Server-Sync](../contracts/server-sync-v1.md).

KiraBridge-Codebefunde beziehen sich auf `d2edeb6`; die live abgefragte dynamische Discovery ist ein eigener Betriebsbefund. Der gemeinsame Thread wurde während dieses Auftrags mit beobachteter Revision 66 gelesen und nennt jüngere parallele RC17-Arbeiten als die alte Reparaturdokumentation. Dieser Plan ändert weder deren Quelle noch deren Status. Offene GitHub-Issue [58](https://github.com/landjunge/threaddesk/issues/58) bestätigt die weiterhin gültige Produktgrenze: Kontext und Stand erhalten; externe Agentenausführung bleibt außerhalb des ThreadDesk-Kerns.
