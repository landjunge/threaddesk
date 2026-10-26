# TD-20261026-FUNC — Funktionsprüfung

Stand: 26.10.2026, Session `/root/functional_audit`. Geprüfter Quellstand: `07e10bf10ad24084becb8ae24e869a624f0b16d1` in `/Users/landjunge/threaddesk-worktrees/codex2-file-receiver-20261024`. Keine Repositorydateien oder Produktivdaten geändert. Testdaten ausschließlich in neuen temporären Verzeichnissen. AGENTS.md des Hauptordners und maßgeblichen Workflow gelesen.

## Ergebnis

68 unterschiedliche ausgewählte Testfälle bestanden; keine offene Testfehlfunktion nach Auflösung der Testumgebung. Zusätzlich **ein reproduzierbarer P1-Funktionsfehler** außerhalb der bestehenden Tests: Die Notizbearbeitung in zwei alten Browseransichten überschreibt neuere Inhalte ohne Konfliktmeldung, sowohl mit JSON als auch SQLite. Eine bestandene Kernabnahme ist kein Beleg für vollständige Fehlerfreiheit.

## Bestätigter Fehler FUNC-BUG-01 — veraltete UI-Notiz überschreibt neueren Stand

Priorität P1, potentieller Verlust neuer Notizinhalte. Zwei Clients öffnen bei Revision 2 denselben Thread. A speichert eine neuere Notiz. B speichert anschließend einen Entwurf aus seiner älteren Ansicht. Beide HTTP-Antworten sind 200; B ersetzt die Notiz von A ohne Revisionsprüfung gegen den Ansichtsstand.

Ursache:

- `src/threaddesk/ui/server.py:776`–784: `/threads/{thread_id}/note` nimmt nur Text und append entgegen, keine erwartete Revision oder persistente Operationskennung.
- `src/threaddesk/api/service.py:327`–335: `set_note` liest unmittelbar den aktuellen Thread neu, setzt den übergebenen alten Inhalt ein und speichert diese bereits aktuelle Revision. Die Store-Revisionsprüfung erkennt deshalb die alte Browseransicht nicht.
- `src/threaddesk/ui/templates/partials/notes.html:8`: Formular enthält CSRF, Text und append, aber keine Revisions-/Operationsbindung.
- Entsprechendes Muster bei Beschreiben (`service.py:339`) und weiteren älteren UI-Mutationen; deren einzelne Konfliktfälle sind hier **nicht separat reproduziert** und als Prüfumfang einzuplanen.

Repro-Datei: `/tmp/threaddesk-team-20261026/repro-stale-edit.py`.

Exakter Aufruf vom geprüften Repo:

```sh
PYTHONPATH=src:tests /Users/landjunge/threaddesk/.venv/bin/python -B /tmp/threaddesk-team-20261026/repro-stale-edit.py
```

Beobachtete Ausgaben des identischen vor Dateispeicherung ausgeführten Skripts:

```json
{"backend": "json", "first_status": 200, "stale_status": 200, "before_revision": 2, "mid_revision": 3, "after_revision": 4, "fresh_note": "fresh edit A", "final_note": "stale edit B"}
{"backend": "sqlite", "first_status": 200, "stale_status": 200, "before_revision": 2, "mid_revision": 3, "after_revision": 4, "fresh_note": "fresh edit A", "final_note": "stale edit B"}
```

Reparaturauftrag FUNC-FIX-01: UI-Schreiboperationen an erwartete Threadrevision und persistente Operationskennung binden; vorhandenen `thread_manage`-Vertrag wiederverwenden, keine zweite Mutationslogik. Konflikt als 409 bzw. vorhandene maschinenlesbare Konfliktantwort anzeigen; Entwurf sichtbar erhalten. Unsichere Antworten über Operationsstatus abgleichen. Abnahme mit zwei Ansichten, konkurrierendem MCP-Schreiben und Wiederholung nach verlorener Antwort jeweils auf JSON/SQLite. Der aktuelle Store-Inhalt darf bei veralteter Ansicht nicht geändert werden; Wiederholung derselben Operation erzeugt keinen zweiten Effekt.

## Tatsächlich ausgeführte Prüfungen

Gemeinsame Isolation: `audit_home=$(mktemp -d /tmp/td-functional-....XXXXXX)`, `HOME="$audit_home" THREADDESK_HOME="$audit_home/workspace" PYTHONPATH=src:tests`, `-p no:cacheprovider`, `--basetemp="$audit_home/pytest"`, JUnit im selben temporären Verzeichnis.

1. Grundprüfungen:

```sh
python3.11 -m pytest -q -p no:cacheprovider tests/test_mvp.py tests/test_storage_contract.py tests/test_thread_management.py tests/test_ui_server.py tests/test_desktop_runtime.py tests/test_build_identity.py --basetemp="$audit_home/pytest" --junitxml="$audit_home/functional.xml"
```

Ergebnis: 49 bestanden, 11 fehlgeschlagen aufgrund fehlender `jinja2`/Threaddesk-Distributionsmetadaten in der globalen Python3.11-Umgebung. Kein Produktfehler daraus abgeleitet. JUnit `/tmp/td-functional-audit.1d5shF/functional.xml`.

2. Ausschließlich diese 11 betroffenen Fälle mit vorhandener vollständiger Testumgebung:

```sh
/Users/landjunge/threaddesk/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_thread_management.py::test_real_stdio_peer_uses_fixed_home_and_operation_receipts tests/test_ui_server.py tests/test_desktop_runtime.py::test_real_package_self_test_never_initializes_user_workspace --basetemp="$audit_home/pytest" --junitxml="$audit_home/functional.xml"
```

Ergebnis: 11 bestanden, 0 fehlgeschlagen, 0 übersprungen, 5.18s. JUnit `/tmp/td-functional-rerun.zQVj9k/functional.xml`.

3. Bibliothek, Backup und Neustart:

```sh
PLAYWRIGHT_BROWSERS_PATH=/Users/landjunge/Library/Caches/ms-playwright /Users/landjunge/threaddesk/.venv/bin/python -B -m pytest -q -p no:cacheprovider tests/test_library_receive.py::test_restart_retry_receipt_search_and_download tests/test_library_receive.py::test_real_stdio_process_resumes_and_reads_receipt tests/test_library_receive.py::test_conflicts_incomplete_checksum_and_abort tests/test_workspace_backup.py::test_backup_manifest_and_verified_restore_match_exactly tests/test_desk_browser.py::test_user_keeps_notes_and_snapshot_across_restart --basetemp="$audit_home/pytest" --junitxml="$audit_home/edges.xml"
```

Ergebnis: 7 bestanden, 1 Browserfall wegen fehlender erwarteter Chromium-Revision 1243 übersprungen. JUnit `/tmp/td-functional-edges.xxLIiB/edges.xml`.

4. Nur den übersprungenen Browserfall mit explizitem vorhandenen Browser nachgeholt:

```sh
THREADDESK_CHROMIUM='/Users/landjunge/Library/Caches/ms-playwright/chromium-1248/chrome-mac-x64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing' /Users/landjunge/threaddesk/.venv/bin/python -B -m pytest -q -p no:cacheprovider tests/test_desk_browser.py::test_user_keeps_notes_and_snapshot_across_restart --basetemp="$audit_home/pytest" --junitxml="$audit_home/browser.xml"
```

Ergebnis: 1 bestanden, 0 übersprungen, 14.48s; eigener lokaler Serverprozess, synthetischer Workspace, Chromium headless. JUnit `/tmp/td-functional-browser.dySOQ9/browser.xml`. Ein vorheriger Versuch lieferte vorübergehend „file not found“, 0 Tests (Checkout wurde parallel durch Koordinator auf main gestellt); Wiederholung des unveränderten Aufrufs erfolgreich. Diese Nullsammlung zählt nicht als Test.

Gesamt eindeutige Fälle: 49 + 11 + 7 + 1 = 68. Kein Vollsuitelauf, keine vorsorglichen Wiederholungsschleifen.

## Funktionsinventar und Planumfang

- Threads/Notizen/Snapshots/Archiv: `api/service.py`, `services/thread_management.py`, UI-Formulare, JSON-/SQLite-Stores. Getestete Kernverträge grün; Revisionsbindung der alten UI als P1 reparieren.
- Bibliotheksdateien/Empfang: `services/library_import.py`, `library_receive.py`, eigener Empfangsvertrag. Restart, Fortsetzen, Quittung, Konflikt, Checksumme und Download gezielt grün. Kein echter Nutzertransfer ausgeführt.
- Backup/Wiederherstellung: `storage/workspace_backup.py`, `portable_backup.py`, `library_backup.py`. Geprüfter manifester Roundtrip auf beiden Backends grün; keine volle Wiederherstellung realer Nutzerdaten.
- Desktop: Startisolierung, Portvertrag und Buildidentität grün. Snapshot/Notiz-Neustart in realem Browser grün. Native installierte App wurde nicht verändert oder vollständig neu abgenommen.
- Wissen/Graph/Whiteboard/Handoffs/Rückgaben: vorhanden, aber in dieser fokussierten Prüfung nur durch Storage-/Verwaltungsverträge berührt. Separate Vertragsabnahme im Integrationsplan behalten.
- Raum-/Server-Sync, Migration, Hausmeister, Exportformate: in dieser Runde nicht praktisch abgenommen; Aussagen zur Funktionsfähigkeit daraus unzulässig.

## Vorhandene Reparaturbelege und Grenzen

`/Users/landjunge/ThreadDesk-Backups/latest-20261026T145414Z/evidence/snapshot-ui-race-fix-summary.json` beschreibt einen bereits erledigten Race-Fix gegen verspätete UI-Antworten nach Snapshot-Restore. Der dort dokumentierte SHA256 von `src/threaddesk/ui/static/app.js` stimmt mit dem hier geprüften HEAD überein: `5c0ed312636f3646d4f9c02690de87e16c55c6575005930c2d7f1d859bae032c`. Dieser alte Fehler soll nicht nochmals als offen geführt werden. Der Beleg benennt selbst die Grenze: keine allgemeine serverseitige Ordnungsgarantie für konkurrierende Schreiboperationen.

Die bestehende `.venv` liefert Paketmetadaten 0.1.0 trotz eingelesenem Quellstand 0.1.2. MCP `serverInfo.version` folgt in `ui/mcp_stdio.py:14` den installierten Metadaten. Dies ist belegter Umgebungsdrift; ein sauber gebautes/installiertes Wheel und eine getrennte Quell-/Paket-/Appidentität sind für die Endabnahme nötig. Daraus allein kein Produktionsdefekt behauptet.

## Priorisierte Folgeschritte

1. P1 UI-Konfliktschutz und Idempotenz mit vorhandenem Mutationsvertrag angleichen, mit reproduziertem Zwei-Client-Fall als Regression.
2. P1 genaue Laufzeitmatrix aus Quellcommit, Wheel, MCP-Peer, Browser/App und Datenprofil festhalten; dynamischen Katalog aus real konfiguriertem Peer prüfen (Teamkollege).
3. P2 noch ungeprüfte Bereiche anhand konkreter Anforderungen sequenziell abnehmen; Laufzeitfehler von historischen/behobenen Befunden unterscheiden.
4. P2 UI-Routen in Fachbereiche modularisieren, während ThreadService kompatible Fassade bleibt; keine Logik-/Speicherdoppelung. Architekturdetail bei zuständigem Teamkollegen.

Abschlusskriterium dieser Diagnose erfüllt: Inventar + fokussierte Testbelege + reproduzierter offener Fehler + präzise Reparaturabnahme. Fehler ist diagnostiziert und noch nicht behoben; kein Releasefreigabeanspruch.
