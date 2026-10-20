# E08.1 / TD-07: optionaler lokaler Inhaltsschnitt

Basis: ThreadDesk main `88a5b4d432d4e221d0e6de4de9da2b1440efdb1d`
(integriertes TD-02/PR #79). Vorhandenen sauberen TD-01-Worktree wiederverwendet;
eigene Branch `feat/e08-local-thread-search-20261020`, keine Installation,
Produktdaten, Dienste, fremden Datenbanken oder Abhängigkeiten verändert.

Implementierung und Bedienung: [LOCAL-SEARCH.md](../../LOCAL-SEARCH.md).
Kleine eigene Core-/Service-/Storage-/CLI-Module; kanonische Speicherform,
Store-Protokoll, Room-/HTTP-/MCP-Registrierungen und Teamrechte bleiben erhalten.
Der Suchweg selbst benutzt keine Legacy-Getter/-Listen und schreibt keine Anker.

## Tatsächliche Gegenproben

`tests/test_local_search.py` prüft JSON und SQLite: aktuellen Titel/Beschreibung/
Notiz, Initialaufbau, Save/Rename/Delete, Archive/Unarchive, echten Snapshot-
Restore, Revision/Originalfeld, Quellreinheit, Default-aus, fehlende Authority,
projektunabhängige Rechte, frischen Widerruf, Cursorbindung, Neustart, Legacy-
Inplace-Edit, über 1000 Threads, Quellen-/Bytegrenzen, defekten/fehlenden Index,
No-FTS-Modul und echten CLI-Einstieg. Beschädigte optionale Konfiguration lässt
kanonisches Speichern zu. Keine Produktdaten als Testfixture.

`tests/test_search_storage_failures.py` enthält echte SQLite-Triggerproben für
`RAISE(ROLLBACK)` und isoliertes `RAISE(ABORT)` beim optionalen State-Write sowie
eine Quellenfehler-Budgetprobe. Im Implementierungsentwurf waren die beiden
letzten Fälle rot (alter FTS-Modus blieb bereit / 500 fehlerhafte Reads ohne
Byteanrechnung). Der endgültige Schnitt entzieht zuerst den Veröffentlichungs-
marker und reserviert Fehlerreads konservativ. Engine-Rollback wird nicht als
kanonischer Save-Erfolg verschluckt. Das sind korrigierte Entwurfsbefunde, keine
erfundene Regression einer vorher vorhandenen Inhaltssuche.

Erweiterter Storage-/Backup-/CLI-/i18n-Lauf: **365 bestanden**, zwei bekannte
Warnungen (Starlette/httpx und absichtlicher doppelter ZIP-Manifestname). Module:
`test_local_search`, `test_search_storage_failures`, `test_storage_contract`,
`test_thread_management`, `test_atomic_import`, `test_room_boundaries`,
`test_room_sync`, `test_json_control_paths`, `test_cli_numbering`,
`test_characterization`, `test_i18n`, `test_workspace_backup`,
`test_portable_backup`, `test_json_migration` unter `tests/`.
Nach der abschließenden Behandlung unterbrochener SQLite-Queries erneut nur
Such-/Fehlerfälle: **67 bestanden**, einschließlich FTS-/Fallback-Fortsetzung
nach INTERRUPT und Backup/Restore bei beschädigtem optionalem Suchzustand.
Funktionstests verwenden eine deterministische Service-Uhr; eine gesonderte
Zeitbudgetprobe prüft den Stopp/Fortsetzungsvertrag. Der reale Benchmark verwendet
die tatsächliche Uhr. Keine Addition überlappender Testläufe und keine daraus
abgeleitete vollständige native CI oder unabhängige Abnahme. Unabhängiges Review
koordiniert der Root-Agent.

## Reproduzierbare Textmessung

```sh
PYTHONPATH=src python scripts/benchmark_content_search.py \
  --sizes 10000 --samples 1000 --scratch /tmp/td-content-10k-new \
  --output /tmp/td-content-10k-results.json
PYTHONPATH=src python scripts/benchmark_content_search.py \
  --sizes 100000 --samples 1000 --scratch /tmp/td-content-100k-new \
  --output /tmp/td-content-100k-results.json
```

Der Runner verlangt einen neuen leeren Scratch-Ordner und markiert ausschließlich
synthetische Korpora. Titel, Beschreibung und echte DE-/EN-Notiztexte mit 2/8/64
KiB Verteilung, seltenen/fehlenden Begriffen, Projekt-/Archivfilter und 30 Prozent
Policy-Denials; tatsächliche UTF-8-Volumina werden gezählt. Quellen, Befüllung,
expliziter Indexaufbau, Kandidatenkern, vollständiger Suchservice und 20 echte
CLI-Prozesse werden getrennt gemessen. Kalter Lauf bedeutet neuer Prozess, keine
gelöschten OS-Caches. Je Profil 1000 warme Service- und Kernmessungen; erste 20
Treffer folgen tatsächlich den Service-Cursorn. Fehlende erste 20, Teilstände
und ein Benchmark-Abbruch nach 250 Seiten werden separat ausgewiesen.

CPU und Peak-RSS sind je separatem Prozess ausgewiesen; der Kandidatenkern liest
allein keine Inhalte und wird niemals als Inhaltsdurchsatz ausgegeben. CLI nutzt
die tatsächliche lokale File-Access-Policy, nicht die synthetische Deny-Policy.
Eine einzelne CLI-Seite darf am Arbeitsbudget Teilstand bleiben; erfolgreiche
erste 20 und deren Latenzen werden getrennt gezählt. Standardgrenzen: 384 MiB
RSS pro Prozess zwischen Batches/Messungen geprüft, 4 GiB Scratch zwischen
Erzeugungsblöcken/Profilen, keine harte Betriebssystem-Sandbox. Keine Dienste
gestartet, keine OS-Caches geleert. Niedrige CPU-Priorität berücksichtigt den
parallel angekündigten nativen Rust-Build; Messungen sind kein isolierter SLO-
oder Produktfreigabebeleg.

Aktueller Status: 200-Thread-Smoke ausgeführt; der erste echte 10k-Aufbau hat
quadratische FTS-Löschung nach `UNINDEXED entity_id` aufgedeckt. Direkte, in der
Projektion gespeicherte FTS-rowids ersetzen diesen Scan. Der nächste reale Lauf
hat unter Last einen falsch als `index_changed` gemeldeten Progresshandler-
Abbruch gefunden; INTERRUPT/BUSY halten jetzt dieselbe Keyset-Position als
Teilstand für die Fortsetzung. Beide frühen Messläufe sind **kein** fertiger
Leistungsnachweis. Neue 10k-/100k-Messungen vom eingefrorenen Reviewkandidaten
stehen noch aus. Keine p95-/Vollständigkeitszusage vor tatsächlichem Resultat.
Messartefakte bleiben privat; eine kompakte volumen-/umgebungsgebundene
Zusammenfassung folgt nach den tatsächlich abgeschlossenen Läufen.

E08 bleibt teilweise offen: E08.1 erhält diesen lokalen Reviewkandidaten;
Teamrechte bleiben E06, Bridge-Dateiindex und produktive Leistungs-/Paketabnahme
sind nicht implementiert oder als bestanden ausgewiesen.
