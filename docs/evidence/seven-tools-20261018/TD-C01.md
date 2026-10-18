# TD-C01 – begrenzte M1-Abnahme / bounded acceptance

Auftrag `seven-tools-build-20261018-1833`, Worker `threaddesk_m1`.
Basis `f67fb59124bc7a0c8343ca8602459094c2962a42`, eigener Worktree/Branch
`threaddesk-worktrees/seven-tools-m1-20261018`, `feat/seven-tools-m1-20261018`.
Fremden dirty Root, alte Arbeitsstände und laufende Sitzungen nicht geändert.

## Implementiert / implemented

- Fachmutationen verwenden vorhandene ThreadService-Methoden, ergänzt um
  Zuordnungsmetadaten und strikte IDs. Projekt = existierender KnowledgeNode;
  Eltern-/verknüpfter Thread = existierende Thread-ID, keine Dateisystembewegung.
- `thread_manage` plus rein lesender `thread_operation_status`, additive
  Revision/Organisation in get/list. Vollständiger Vertrag: [MCP](../../MCP.md).
- Persistente Operations-ID/Requesthash/Originalergebnis; gleiche Anfrage einmalig,
  geänderte Anfrage Konflikt. Archiv vor Löschung, Löschbeleg bleibt erhalten.
- Legacy/UI/CLI-Saves prüfen/erhöhen Revision. JSON-Inhaltshashanker erkennt
  nachträglich beobachtete Änderungen alter Writer, auch bei verlorenem Revisionfeld.
- SQLite Schema5 additive Receipt-Tabelle; atomarer Zustands-/Belegcommit.
  JSON Zustand+Receipt als wiederherstellbarer Writeahead-Zustandsplan unter
  lokaler Sperre. Kein erneutes Ausführen des ursprünglichen Kommandos beim Recovery.
- JSON→SQLite und portable Backups erhalten Belege; macOS-Symlinkguard bleibt
  innerhalb des Workspaces strikt, verwechselt aber /var nicht mit einem
  eingeschleusten Workspace-Symlink.
- MCP initialize nutzt installierte Paketmetadaten, keine erfundene Quellversion.
  `THREADDESK_HOME`/`THREADDESK_STORAGE` und bestehende Profilwahl dokumentiert.

## Tatsächliche Prüfungen / observed checks

Alle Proben nutzten isolierte temporäre Workspaces und synthetische Daten.
Keine Nutzerthreads, echten Konten, Agenten- oder Provideraufrufe.

- `pytest tests/test_thread_management.py tests/test_mcp.py tests/test_storage_contract.py`
  erster Kernstand: **24 bestanden**. Neuer Schema-Test wurde ausdrücklich von4
  auf5 fortgeschrieben; kein vorhandenes Schema heimlich überschrieben.
- Kompatibilitätsprobe `test_mvp.py`, `test_json_migration.py`,
  `test_characterization.py` gemeinsam mit neuer Verwaltung: **33 bestanden**
  nach Korrektur des Imports bereits revisionierter Threads und erwarteter
  additiver öffentlicher Felder. Bestehender Migrationsstand bleibt erhalten.
- Nach Legacy-Hashanker: M1/Migration/Charakterisierung **26 bestanden**.
- Nach rein lesendem Statusabruf: M1/Charakterisierung **23 bestanden**.
- Letzte auf neue Fälle beschränkte Probe `test_thread_management.py` und
  `test_portable_backup.py`: **25 bestanden**. Zwei bestehende Warnungen:
  Starlette/httpx-Deprecation und absichtlich doppelte ZIP-Testmanifest-Datei.
- `python scripts/check_release_inputs.py`: **209 Dateien geprüft**, keine
  verbotenen Runtime-Dateien im damaligen versionierten Stand.

Abgedeckt: create/read/update/notes/file references/organization/switch/archive/
unarchive/delete/read-back, identischer create/delete, ID-Kollision, veralteter
UI-Schreibstand, falsche IDs/Typen/owner-Felder, zyklische Zuordnung, Rollback bei
teilweise ungültigem Update. Vier parallele gleiche create-Anfragen erzeugen
auf beiden Backends genau einen Thread. JSON-Abbruch **nach dauerhaftem Plan und
erstem Datenwrite** erholt denselben Zustand/Beleg beim Neustart. Echte lokale
stdio-Probe: initialize, initialized ohne Antwort, create und Statuslookup.

## Grenzen / limits

Implementiert und gezielt geprüft; keine Nutzerabnahme, Desktop-Neuveröffentlichung
oder tatsächliche ChatGPT-KiraBridge-Ende-zu-Ende-Abnahme behauptet. Der neue
Gesprächsweg benötigt einen explizit konfigurierten lokalen Peer/Workspace und
separate Bridge-Rechte. Installierter Desktop0.1.1rc1 enthält diese Tools nicht.
Schema5 setzt aktuellen SQLite-Writer voraus. Alte JSON-Writer ohne gemeinsame
Sperre dürfen nicht gleichzeitig denselben veränderlichen Workspace bedienen;
beobachtbare spätere Änderungen werden erkannt, unbemerkter change-and-restore
oder absichtliche Manipulation von Daten und Hashanker nicht garantiert erkannt.

Keine Oberfläche verändert; bestehendes DE/EN/Layouts bleiben erhalten.
PR66 ist weiterhin separat offen, nicht pauschal integriert. Neue API- und
README-Texte führen DE/EN, Code-/Paket-/Abnahmestand getrennt. M2 bleibt eigenes
Folgepaket; Kontextverwaltung startet keine externe Arbeit.
