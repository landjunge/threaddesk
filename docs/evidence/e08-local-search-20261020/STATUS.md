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
Byteanrechnung). Der Schnitt reserviert Fehlerreads konservativ. Engine-Rollback wird nicht als
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

Unabhängiges Review auf `b966bd7` fand zusätzlich einen isoliert verweigerten
FTS-Marker-DELETE: Rename wurde kanonisch gespeichert, aber der alte Index blieb
`ready`, neue Wortsuche lieferte fälschlich vollständig null Treffer. Die
unveränderte Reviewer-Gegenprobe ist nun in den Regressionen enthalten. Zuerst
wird ein unabhängiger `epoch`-/`stale`-Stand geschrieben, danach der Marker
geändert. Scheitert bereits der State-Write isoliert, entzieht der alternative
Markerweg die Veröffentlichung. Beide einzelnen Fehlerwege und echter
Engine-Rollback sind erneut geprüft. Der getrennte Steuerzeichen-Nit ist durch
Ablehnung von C0, DEL und C1 erfüllt, ohne Normalisierungs-/Suchsemantikwechsel.
Nach dieser engen Korrektur: **86 bestanden**, davon 74 Repositoryfälle und
12 unveränderte private Reviewerfälle; keine Addition zu den früheren Läufen.

Ein weiterer unabhängiger Gegenfall auf `b8da29d` betraf einen Save während
der Policyprüfung: isolierter State-ABORT ließ den Epochstring gleich. Sowohl
FTS-Moduswechsel als auch bereits aktiver Scanmodus konnten dadurch eine alte
Seite zurückgeben. Die vorhandene dauerhaft getrennte read-only-Verbindung
liefert jetzt einen zusätzlichen verbindungslokalen `data_version`-Beobachter;
der Abschluss vergleicht außerdem Enabled-Stand/Quellmodus. Der stärkere
Reviewerfall installiert den Fehlertrigger bereits vor Seitenbeginn, sodass
nur der echte kanonische Save während der Seite committet. Keine Schema-, WAL-
oder globale Snapshotgeneration wurde ergänzt. Die unveränderten privaten
Reviewerproben sind erneut grün: **92 bestanden** (76 Repositoryfälle plus
16 unveränderte private Reviewerfälle), einschließlich beider FTS-/Scan-Fälle
ohne DDL während der Seite. Keine Addition zu den überlappenden früheren Läufen.

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

Früher Messstatus: 200-Thread-Smoke ausgeführt; der erste echte 10k-Aufbau hat
quadratische FTS-Löschung nach `UNINDEXED entity_id` aufgedeckt. Direkte, in der
Projektion gespeicherte FTS-rowids ersetzen diesen Scan. Der nächste reale Lauf
hat unter Last einen falsch als `index_changed` gemeldeten Progresshandler-
Abbruch gefunden; INTERRUPT/BUSY halten jetzt dieselbe Keyset-Position als
Teilstand für die Fortsetzung. Beide frühen Messläufe sind **kein** fertiger
Leistungsnachweis.

Die vollständige 10k-Messung auf **`b966bd7` vor dem unabhängigen Reviewfix** ist
inzwischen abgeschlossen: macOS 15.7.4 Intel/x86_64, 4 logische CPUs, 32 GiB RAM,
Python 3.12.13/SQLite 3.53.2, `nice 10`, keine geleerten OS-Caches. Je Backend
40.372.400 UTF-8-Textbytes (270.000 Titel, 1.600.000 Beschreibung, 38.502.400
Notizen), 1000 warme Messungen mit jeweils tatsächlich erreichten ersten20.

| Modus | Service p50 / p95 ms | Service CPU p50 ms | Service Peak-RSS MB | echte CLI p95 ms / erste20 |
| --- | --- | --- | --- | --- |
| FTS5 | 10,48 / 39,99 | 8,89 | 44,8 | 687,78 / 20 von20 |
| SQLite bounded scan | 6,60 / 22,68 | 5,91 | 40,1 | 653,53 / 20 von20 |
| JSON bounded scan | 59,75 / 158,95 | 56,62 | 33,7 | 428,33 / 20 von20 |

Das JSON-Profil verfehlt das vorgeschlagene warme 100ms-Ziel in dieser Umgebung.
Alle dichten ersten Seiten haben reguläre Fortsetzungen; das ist kein Fehler
und keine vollständige Bestandssuche. JSON bleibt zusätzlich immer ausdrücklich
`json_external_writers_unverified`. Kernel, kalter Prozess, CPU/RSS der CLI,
Aufbau, exakte Quellhashes, Teilstände und seltene/fehlende Suchbegriffe stehen in
[der kompakten Messdatei](benchmark-10000-b966bd7.json); rohe Stichproben privat.
Diese historischen Werte werden den nachfolgenden Korrekturbytes **nicht**
zugeschrieben.

Die vollständige **100k-Messung auf `b8da29d` vor dem Inflight-Fix** liegt separat
in [benchmark-100000-b8da29d.json](benchmark-100000-b8da29d.json): dieselbe
Umgebung, 403.724.000 tatsächliche UTF-8-Textbytes je Backend, 1000/1000 warme
Serviceproben mit erreichten ersten20. Service p95 FTS5 11,64 ms, SQLite-Scan
24,39 ms, JSON 56,65 ms; Service-RSS 45,3/40,1/33,8 MB. Die einzelne echte
CLI-Seite erreicht erste20 nur in18/20,20/20,19/20 Aufrufen; übrige Aufrufe sind
am Zeitbudget partiell und in der Messdatei als solche aufgeführt. JSON-
Fixtureerzeugung 394,7 s ist eigener Aufbauaufwand, kein Suchwert. Die
100k-Indexbefüllung benötigte 25,34 s. Hardware neben den eingebetteten Werten:
Intel i5-6500 3,20 GHz, iMac17,1; tatsächliche Scratch-Belegung blieb unter4 GiB.
Die verschiedenen Pins und veränderliche konkurrierende Hostlast erlauben
keinen direkten Größen-/Backend-SLO-Vergleich. Beide fertigen historischen
Läufe haben `source_dirty=false` und geprüfte Sourcehashes. Finale Quellbytes
erhalten eine eigene Messzuordnung; kein vollständiges E08.3 oder Produktgate.

E08 bleibt teilweise offen: E08.1 erhält diesen lokalen Reviewkandidaten;
Teamrechte bleiben E06, Bridge-Dateiindex und produktive Leistungs-/Paketabnahme
sind nicht implementiert oder als bestanden ausgewiesen.
