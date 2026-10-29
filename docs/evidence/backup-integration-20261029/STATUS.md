# Backup-v3-Integration, 29. Oktober 2026

Auftrag `codex2_backup_integration_20261029`: **im Entwicklungszweig integriert und gezielt getestet, zur Prüfung in der bestehenden PR #95 vorbereitet.** Kein Merge nach main und keine produktive Installation.

Der vorgesehene Zweig ist `feat/remaining-plan-20261027` bei `6cc3763`, bereits Gegenstand von [PR #95](https://github.com/landjunge/threaddesk/pull/95). Der geprüfte Quellfix `05a7022fb63e94fa0c94bd35aa8682aff1cd0700` wurde mittels `git cherry-pick -x` als `f10fb10cbc10fa2b78acc6a0d38114af06699861` übernommen. Unabhängige Prüfung bestätigt den identischen vollständigen Gitbaum, identischen binären Parentdiff und identische Bytes aller zehn betroffenen Dateien. Es gibt weder eine zweite Implementierung noch einen konkurrierenden Backup-PR. Diese Belegdateien kommen als separate Dokumentation hinzu; Laufzeitcode und Tests bleiben exakt auf dem geprüften Stand.

Vor der Übernahme wurden sämtliche 22 bisherigen Sicherungs-/Belegdateien anhand des vorhandenen Manifests erneut hashgeprüft. Die neue lokale Datei `Betroffener-Abschnitt-vor-Integration.tar.gz` enthält beide Fassungen der betroffenen Dateien (18 vorhandene Dateien; die zwei Neudateien fehlen erwartungsgemäß im Ausgangsstand). Jeder Archivinhalt wurde rückgelesen und mit der Quelle verglichen. SHA-256: `0051c8473d850c8d869782c495b962e4207c0bfc7a5dc66714c81cb657e376e5`. Lokaler Belegordner: `/Users/landjunge/ThreadDesk-Backups/backup-integration-20261029/`.

## Kompatibilität und Regression

**254 Prüfungen bestanden, keine Fehler oder übersprungenen Fälle.** [Maschinenlesbare Prüfdaten](checks.json) enthalten Module, JUnit-/Loghashes, Zähler, Codeidentitäten und Archivprüfsummen.

- 190 Backup-/Library-/Workspace-/Betriebsfälle bestanden, darunter alle 58 Streamingfälle in diesem einen Lauf. Enthalten sind v1/v2-Restore mit Bytes, Dateipfad und Seek-Stream für JSON/SQLite, 129 MiB, 20.010 Dateien, ZIP64, Manipulation, inerte Links, Verzeichnisse und Revisionsanker.
- 64 HTTP-/CLI-/Recovery-/Vertrags-/Browserfälle bestanden. Die vier echten Daten-Browserfälle prüfen Download, Restore in ein neues Profil und Rückkehr zum unveränderten isolierten Original für JSON und SQLite. Chrome war bereits vorhanden; es wurden ausschließlich temporäre Testprofile verwendet.
- Beide bestehenden realen v3-Vollarchive wurden unter dem Integrationscode erneut vollständig mit `inspect_backup` geprüft: Desktop 28.237 Dateien / SHA-256 `7ab3bf5f7163e918b975c076c2b10b55f3f6637b946e40424c2aeb89e6ea8634`; Operator 680 Dateien / `243634f279ca5e32727220964d20e1b8839809c3497de07851e33a6df19719dc`.
- Das tatsächlich vorhandene v2-Archiv der Brainstorm-Teilsicherung wurde ebenfalls vollständig geprüft: 4.048 Dateien / `1ce966378116478675b14734ce616b77299475b9bb27216c6015c8bf4b0918cd`. Die Legacytests belegen v1 zusätzlich; ein historisches reales v1-Archiv wird nicht behauptet.
- Geänderte Kern-/Commandmodule bestehen Ruff; `git diff --check` ist sauber. Der vorbestehende UI-Server-Gesamtlint wurde hier nicht als fehlerfrei erklärt. Warnungen betreffen den vorhandenen Starlette/httpx-Testclient und das absichtlich doppelte ZIP-Mitglied eines Angriffstests.

Reproduktion aus dem Integrationsworktree mit Python 3.12 und installierten Projekt-Testabhängigkeiten:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m pytest -q tests/test_portable_backup_streaming.py tests/test_portable_backup.py tests/test_library_backup.py tests/test_workspace_backup.py tests/test_operational_commands.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src THREADDESK_CHROMIUM='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' python -m pytest -q tests/test_http_access.py tests/test_commands.py tests/test_packaged_commands.py tests/test_command_recovery.py tests/test_command_catalog_contract.py tests/test_data_browser.py
```

## Freigabegrenze

Die bisherigen v1/v2-Formate bleiben lesbar. Der neue v3-Leser ist im Entwicklungszweig enthalten; die installierte App v0.1.5 bleibt unverändert und kann v3 weiterhin nicht öffnen. Die vollständigen isolierten Restores beider realen v3-Archive aus dem Vorauftrag bleiben gültige Belege, weil der integrierte Code identisch ist. Hier wurden weder die Daten erneut exportiert noch eine weitere Vollkopie angelegt; die neuen Restoretests verwenden ausschließlich erzeugte Testprofile.

Die letzte erfolgreiche vollständige PR-CI gehörte zum alten Pin `6cc3763`. Die neue PR-CI und die bisherigen weiteren PR-95-Gates bleiben bis zu ihrem tatsächlichen Abschluss offen; 254 gezielte lokale Fälle ersetzen keine komplette CI-/Paketabnahme. Veröffentlichungs-/Deploymentwege wurden nicht verändert oder ausgelöst. Kein Merge, Release, produktiver Neustart, Installation, Verschieben oder Löschen von Originaldaten. Andere Terminal-Tabs und die erste Codex-Instanz wurden nicht bedient.
