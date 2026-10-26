# TD-20261026-DYN — Dynamische ThreadDesk-/KiraBridge-Prüfung

Stand: 26.10.2026. Session `/root/dynamic_bridge_audit`. Quellen: ThreadDesk `07e10bf` und KiraBridge `d2edeb6` im vorhandenen Worktree. Nur lesende Prüfung und isolierte Tests; keine Repository-/Produktivänderungen.

## Inventar und Coverage

| Fachbereich | ThreadDesk MCP | KiraBridge | Bewertung |
|---|---|---|---|
| Threads lesen | list_threads/get_thread/current_thread | Dynamische Reads; statische Queue | vorhanden |
| Threads verwalten | thread_manage, 10 Aktionen | threaddesk.manage, Queue | statisch vorhanden, nicht dynamisch schreibbar |
| Snapshots lesen | list_snapshots | dynamisch + Queue-Read | vorhanden |
| Snapshots schreiben | save_snapshot/restore_snapshot | keine allgemeine dynamische Schreibroute | Lücke |
| Knowledge/Reentry | knowledge_manage/get_reentry | Knowledge-Queue + Reentry-Read | teilweise vorhanden |
| Handoff/Return | mehrere Fachtools | eigene Fachwege | vorhandene Fachadapter erhalten |
| Library | library_receive/status/search/file_info | File-Receiver; dynamische Reads | vorhandene Module erhalten |
| Whiteboard/Arbeitsstand | kein MCP-Tool; HTTP-/Service-API vorhanden | weder dynamisch noch Queue-Read | prioritäre Abdeckungslücke |
| Graph/Knoten/Relationen | kein MCP-Tool | kein fachlicher dynamischer Zugang | Abdeckungslücke |
| Akteursverwaltung | kein MCP-Tool | kein fachlicher dynamischer Zugang | Abdeckungslücke |
| Lokale Suche | kein MCP-Tool für SearchService | kein fachlicher dynamischer Zugang | Abdeckungslücke |
| Backup/Profile/Restore/Migration | UI/CLI-/Services, kein allgemeiner MCP-Zugang | kein fachlicher dynamischer Zugang | Abdeckungslücke; Effekte explizit behandeln |
| Rooms/Server-Sync | Services/UI, kein allgemeiner MCP-Zugang | kein fachlicher dynamischer Zugang | Abdeckungslücke; Netzwerk-/Controleffekte |
| Hausmeister/Settings | UI/Services | kein fachlicher dynamischer Zugang | Abdeckungslücke |

Exakte Zählung der aktuellen Quelle: **34 MCP-Tools**, **12 explizit lesend freigegebene Tools**, **62 UI-Routen**. Service-/UI-Anzahl ist keine Zahl fachlicher Funktionen.

Die 12 dynamisch geeigneten Reads: `library_receive_status`, `library_search`, `library_file_info`, `get_reentry`, `get_issued_handoff`, `thread_operation_status`, `list_threads`, `get_thread`, `current_thread`, `list_snapshots`, `list_gnom_jobs`, `check_gate`.

Statische Queue: sechs typisierte Reads, zehn Thread-Manage-Aktionen und vier Knowledge-Aktionen; daneben eigene Handoff-/Return-Fachwege.

## Bestätigte Befunde und Quellen

1. Dynamischer Proxy ist absichtlich ausschließlich lesend: KB `src/kirabridge/threaddesk_dynamic.py:26`, `:34`, `:88`. Live-Antwort des Koordinators `{tools:[],enabled:false}` passt zum Opt-out: `src/kirabridge/bridge_core/config.py:201`, `threaddesk_dynamic.py:79`. Der frühe Return prüft weder Verbindung noch Permissions; daher kein Verbindungs-/Rechtefehler belegt.
2. MCP-Liste und explizite Read-Annotations: TD `src/threaddesk/services/mcp.py:52`, `:252`. Whiteboard existiert als Fachservice: `api/service.py:542`, `:546`, `:558`; HTTP: `ui/server.py:565`, `:574`, `:586`. Es fehlt im MCP-Katalog und den Queue-Reads.
3. KB `read_query.py:15` unterstützt nur file.read/file.list/terminal.output/session.catalog/session.read; kein alternativer Whiteboard-Fachweg. Statische ThreadDesk-Reads und Aktionen: `bridge_core/models.py:126`, `:138`, `:157`, `threaddesk_manager.py:25`.
4. Dynamische Katalogänderungen besitzen keinen eigenen Fingerabdruck: KB `mcp_gateway/proxy.py:37`–`:43` hasht die Basistools des Daemons; `td_`-Tools werden erst `:132`–`:145` ergänzt. Reines Hinzufügen/Entfernen dynamischer Tools erhöht daher change_generation nicht. Erneutes Listing entdeckt Änderungen; automatischer Push ist damit nicht belegt.
5. `_fresh_tools()` verwirft ab 65 deklarierten Peer-Tools den kompletten dynamischen Katalog, auch wenn nur eines lesend ist: `threaddesk_dynamic.py:67`. Isoliert reproduziert: 1 Read + 64 Writes => `threaddesk_tool_limit`. Das ist aktuell eine Erweiterungsgrenze, kein Fehler bei den heutigen 34 Tools.
6. Operationslookup-Semantik unterscheidet sich: Statische Queue namespaced IDs nach Principal/Workspace (`threaddesk_manager.py:97`–`:117`), dynamischer Read reicht sie unverändert weiter (`threaddesk_dynamic.py:111`). Vor einheitlicher Bedienung normalisieren oder logische/physische IDs explizit unterscheiden. Nicht als belegte Sicherheitslücke gewertet.
7. Bestehende Grenzen erhalten: frische Annotationen/Permissions pro Read, Schema-/Namens-/Ergebnisgrenzen, fehlende Annotationen abweisen, keine automatischen Wiederholungen nach unklarem Schreibausgang.

## Prüfungen

Vorhandene Umgebung im KB-Worktree: `.venv/bin/python`; `PYTHONPATH=src` auf den geprüften Stand setzen. Standard-python3 ist hier 3.8 und ungeeignet.

```sh
PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_threaddesk_dynamic.py tests/test_threaddesk_catalog_refresh.py tests/test_threaddesk_contract.py
```

Ergebnis: **55 passed in 6.56s**.

```sh
PYTHONPATH=/Users/landjunge/threaddesk-worktrees/codex2-file-receiver-20261024/src .venv/bin/python -m pytest -q -p no:cacheprovider /Users/landjunge/threaddesk-worktrees/codex2-file-receiver-20261024/tests/test_mcp_readonly_annotations.py
```

Ergebnis: **1 passed in 0.06s**. Zusätzlich synthetischer 65-Tool-Grenzfall erfolgreich reproduziert. Keine Vollsuite, keine Live-Mutation, keine installierte Desktop-Abnahme.

## Plan und Abschlusskriterien

Definition „alle“: Jede fachliche Funktion hat einen dokumentierten Eintrag mit available/disabled/permission_required/unsupported_version oder begründeter lokaler UI-Bindung. Sichtbarkeit und Ausführungsrecht bleiben getrennt.

1. **P0 Inventar:** verbindliche Matrix UI/CLI/MCP/Bridge/Effekt/Storage/Tests; jede UI-Fachaktion zugeordnet oder begründet ausgenommen. Bestehende `ModuleManifest`/`ModuleRegistry` als Modulgrundlage wiederverwenden; keine konkurrierende zweite Modulregistrierung. Diese Wiederverwendung ist Planvorgabe, keine in dieser Prüfung zusätzlich verifizierte API-Detailaussage.
2. **P1 gemeinsame CommandSpec-Registry:** je Domäne stabile Command-ID, Schema, Outputschema, Effekt, Permission, Scope, Revision/Operations-ID-Anforderung und Handler. Auf vorhandene Modulregistrierung aufsetzen. Fachliche Services bleiben Logikquelle; CLI/HTTP/MCP sind Adapter derselben Commands. Keine Introspektion beliebiger Pythonmethoden. Abnahme: keine doppelten Namen, jeder Command hat Handler/Schema, alle veröffentlichten Commands sind einer Domäne zugeordnet.
3. **P2 Reads:** zunächst Whiteboard-Liste/Arbeitsstand, Graph/Knoten/Relationen, Akteure, Returns, Suche/Suchstatus. Mischoperationen wie Vorschau/Speichern trennen. Abnahme: synthetischer neuer Read erscheint ohne KB-Quelländerung; keine fachlichen Datenänderungen durch Reads.
4. **P3 Discovery:** KB-Module für catalog/schema/policy, bestehenden Manager als Fassade erhalten. Revision über Gesamtkatalog einschließlich dynamischer Tools; Vertrags-/Build-/Workspaceidentität; paginierte begrenzte Discovery und sichere Filtergründe. Change-Zustellung tatsächlich implementieren. Abnahme: hinzugefügte/entfernte Tools, Schemaänderungen, Rechteentzug und Reconnect aktualisieren Revision und erreichbare Methoden korrekt. Grenze 64 bewusst gestalten statt schlicht unbeschränkt machen.
5. **P4 dynamische Writes separat:** generischer Invoke-Vertrag über bestehende Queue, keinen zweiten Dispatcher. Fachliche Capability, konkrete Scope-/Objekt-IDs, expected_revision und stabile operation_id. Atomarer persistierter Ergebnisbeleg, Statuslookup und unabhängiger Readback. Whiteboard zuerst; vorhandene Append-Deduplizierung nutzen und Revisions-/Quittungsvertrag vervollständigen. Abnahme: identischer Replay liefert Originalbeleg, geänderte Nutzlast kollidiert, veraltete Revision scheitert, Verbindungsabbruch bleibt unknown, keine automatische Wiederholung.
6. **P5 Domänenwellen:** Threads/Snapshots -> Whiteboard/Akteure -> Knowledge/Graph -> Suche/Library -> Handoff/Returns -> Backup/Profile/Migration -> Rooms/Server-Sync -> Hausmeister/Settings. Bestehende LibraryReceiver-/File-Receiver-/Fachadapter wiederverwenden. Effekte für Restore, Profilwechsel, Export und Netzwerk explizit ausweisen. Pro Domäne Matrix und relevante JSON-/SQLite-Abnahme vervollständigen.
7. **P6 Betrieb:** erst isoliertes Profil und gepinnte Builds, dann reale MCP-Clientabnahme mit überprüftem Paket-/Config-Diff. Opt-in nicht schon jetzt aktivieren. Katalog, einen Read, expliziten Write plus Readback und Offline-Verhalten prüfen. Git-SHA, Paketversion, Source-Pin, Profil und geladenen Runtime-Stand getrennt belegen. Code-Merge ist keine Installation.

Modulgrenzen: Domainmodule kennen keine FastAPI-/MCP-Objekte; Storage hinter bestehenden Protokollen. KiraBridge importiert keine TD-Interna und schreibt keine TD-Datenbank direkt. Vertragsfixtures statt mehrfacher Allowlisten. Begrenzte Schemaübernahme mit Größen-/Tiefengrenzen, keine unkontrollierte $ref-Auflösung. CommandSpec delegiert, kopiert keine Geschäftslogik.

Offen: Live-Opt-in, Produktionsaktivierung, neue fachliche Funktionen und installierte Versionen sind durch diese 56 Tests nicht abgenommen. Fehlender Whiteboard-Fachzugang bleibt dokumentierte P1-Lücke; rohe Datei-/DB-Umgehung ist keine dynamische Integration.
