# Bibliotheksbefehle für Desktop, CLI und MCP

Stand der Vertragsprüfung: 26. Oktober 2026. Die gemeinsame Fachgrenze ist `LibraryApplication.call()` in `services/library_api.py`. CLI, lokaler HTTP-Router und die neuen MCP-Werkzeuge delegieren dorthin. Eine vorhandene Implementierung ist kein Nachweis ihrer Installation oder ihrer Erreichbarkeit für jede KiraBridge-Identität.

Der verbindliche Umfang und die Arbeitspakete stehen weiterhin im [bestehenden Gesamtplan](plans/THREADDESK-GRAPH-PAPIERKORB-BEDIENUNG-20261026.md). Diese Referenz beschreibt die tatsächlich angebotenen Verträge; sie ist kein konkurrierender Ausbauplan. KI-Gedächtnis, neue Graphrenderer und andere früher verschobene Themen gehören nicht zum aktuellen Bibliotheksauftrag.

## Gemeinsame Aufrufwege

| Weg | Aufruf | Ergebnis und Grenze |
| --- | --- | --- |
| CLI | `td library --request '<JSON>'` oder `--request-file /absoluter/anfrage.json` | Eine JSON-Zeile; Erfolg `{"ok":true,"result":...}`, Fehler `{"ok":false,"code":...,"error":...}`. Exit 0 beziehungsweise 2. Anfrage höchstens 128 KiB. |
| Paket-CLI | `ThreadDeskServer --library-command '<JSON>'` | Dieselbe Fachgrenze und JSON-Hülle im tatsächlich entsprechend gebauten Tauri-Sidecar. Der Quellcode-Frontdoor allein belegt noch keine aktualisierte installierte App. |
| MCP lesen | `library_query` mit demselben JSON | Nur die lesenden Aktionen. Vorhandene `library_search`, `library_file_info` und Dateiempfangsverträge bleiben kompatibel. |
| MCP ändern | `library_manage` mit demselben JSON | Explizite Mutationen einschließlich Mac-Öffnen. Ihre Registrierung bedeutet nicht, dass der heutige native KiraBridge-Schreibadapter sie bereits transportiert. |
| HTTP lesen | `GET /api/library/query?action=search&query=...` | JSON-Hülle wie CLI; `include_trashed` nur `true`/`false`; numerische Seitengrenzen werden geprüft. |
| HTTP ändern | `POST /api/library/command`, JSON-Anfragekörper | Bestehende lokale Host-/Origin-/Sitzungsprüfung und CSRF gelten. Der Browser übermittelt `X-ThreadDesk-CSRF`; keine neue ungeschützte Maschinenroute. |
| HTTP Medien | `GET /api/library/content/{record_id}` | Nur zugelassene Bild-/Audio-/Videovorschau, `nosniff`, `no-store` und restriktive CSP. Kein HTML-/SVG-/Skript-Endpoint. |

Das Datenprofil wird wie bei den bisherigen Befehlen mit `THREADDESK_HOME` und `THREADDESK_STORAGE=json|sqlite` ausgewählt. API-Argumente dürfen den Workspace nicht still auf einen fremden Pfad umstellen. Dateipfade in einer expliziten Importanfrage bezeichnen eine autorisierte Quelle, keine Shellbefehle.

## Lesende Aktionen

| `action` | Eingabe | Inhalt |
| --- | --- | --- |
| `status` | keine weiteren Felder | Kompakte Bestandszähler, Import- und Indexzustand; tatsächliche Paket-/Buildidentität. Dateidetails separat über `list`/`import_status`, Formatdetails über `formats`. `historical_inventory_verified=false` ist kein Fehler des Teilimports, sondern die offene historische Quellenprüfung. |
| `formats` | keine weiteren Felder | Unabhängige Fähigkeiten `manage`, `index`, `preview`, `preview_kind`, `external_open`, `index_reason` und die getrennte Aufnahmegrenze `import_allowed`/`import_error` pro registrierter Endung. |
| `search` | `query`, optional `limit`, `offset`, `entity_type`, `thread_id`, `project_id`, `kind`, `date_from`, `date_to`, `assignment`, `include_trashed` | Treffer und Indexstatus. Standarddomäne ist `all`; wählbar sind `file`, `thread`, `node`. |
| `list` | optional `thread_id`, `node_id`, `folder`, `sort`, `include_trashed`, `limit`, `offset` | Dateirecords, logische Unterordner, Gesamtzahl, `next_offset` und Generation. Sortierung `name`, `date`, `size`, `type`. |
| `info` | exakte Datei-`id` | Aktueller Record mit Revision, Prüfsumme, logischem Pfad, Herkunft und Zuordnungen. Papierkorbeinträge sind in der normalen Information gesperrt. |
| `preview` | exakte Datei-`id` | Sicherer Vorschautyp, begrenzter Text beziehungsweise Medienroute, Metadaten, Trunkierungs-/Extraktionsstatus und `can_open`. Papierkorb zeigt nur Metadaten und Wiederherstellungsmöglichkeit. |
| `operation` | `operation_id` | Dauerhafter Ergebnis-/Fehlerbeleg oder ausdrücklicher unklarer Zustand. Eine vorhandene ID mit `status=unknown` ist keine Erfolgsmeldung. |
| `import_status` | Import-`operation_id`, optional `limit`, `offset` | Begrenzte Seite der gespeicherten Jobquittung, Quellenkonflikte, Checkpoints, Graph-/Indexzustand und Fortschritt. Vollständiges Quellenmanifest bleibt privat. |
| `sources` | keine weiteren Felder | Nur ausdrücklich registrierte Quellordner, letzter Versuch/Erfolg, Fehler, fehlende Quelldateien und begrenzte Warnlisten. |

Import- und Resumeantworten sowie der Batchteil von `operation` liefern denselben begrenzten Jobblick. `import_status` beginnt ohne Parameter bei Offset 0 mit höchstens 20 Dateizeilen. Bis zu 50 Dateizeilen pro Seite sind möglich; der aktuelle öffentliche Adapter klemmt Werte 51–100 auf 50, größere oder ungültige Seitengrößen werden abgewiesen. Ein zusätzliches JSON-Budget von 30 KiB kann die tatsächliche Seite verkleinern. Zum Weiterblättern ausschließlich `next_offset` verwenden, nicht den angeforderten `limit` addieren. `returned`, `total`, `expected_count`, `processed`, `remaining` und `page_limited_by_bytes` erklären den Fortschritt. Lange Einzelwerte werden mit `truncated_fields` gekennzeichnet; `file_index` bleibt ein genauer Locator. `manifest` und vollständige private Quellenmetadaten gehören nicht in diese Transportantwort. Das 30-KiB-Budget gilt diesem Jobblick, nicht pauschal allen Bibliotheksantworten.

```sh
td library --request '{"action":"import_status","operation_id":"import-001","limit":20,"offset":0}'
```

Treffer enthalten je nach Domäne `record_id`, `thread_id`, `file_node_id`, `node_id`, bestätigte Projektzuordnungen, Snippet und Navigationspfade. Ein Dateitreffer führt zu Datei und Graphdokument. Alte Originalpfade bleiben als Herkunft suchbar, auch nach Umbenennen oder Verschieben. Historische Quellversionen bleiben erhalten und werden über `version`/`current_version` gekennzeichnet; sie werden nicht automatisch gelöscht.

Volltext und Teilbegriffe verwenden eine lokale SQLite-FTS-Projektion, bei verfügbarer Trigramunterstützung mit echter Teilzeichensuche. Auf älterem SQLite bleibt die definierte Teilbegriffssemantik mit begrenzter SQL-Abfrage erhalten. Unicode-/deutsche Varianten wie `Brücke`, `bruecke`, `brucke` werden normalisiert. Alle Suchwörter müssen vorkommen; Benutzereingabe wird nicht als freie FTS-/SQL-Syntax ausgeführt. Dies ist keine semantische KI-Suche und keine allgemeine Tippfehlerkorrektur.

Die effektive Suchgrenze ist 512 UTF-8-Bytes und höchstens 16 Suchwörter, 1–100 Treffer und Suchoffset höchstens 10.000. Andere Listen können einen höheren Offset erlauben. Datumfilter erwarten ein ISO-Datum und verwenden die indexierten Datumsfelder; unbekannte historische Quelldaten werden nicht erfunden. Veraltete oder beschädigte Projektionen liefern einen Fehler beziehungsweise sichtbaren Zustand statt eines angeblich vollständigen leeren Ergebnisses.

## Schreibende Aktionen und Wiederaufnahme

Jede Mutation benötigt eine stabile `operation_id`. Dateirecordänderungen und `open` benötigen zusätzlich die gelesene `expected_revision`. Eine Operationskennung darf nicht für eine andere Nutzlast wiederverwendet werden. Bei unklarem Ausgang zuerst `operation` beziehungsweise `import_status` unabhängig lesen; nicht blind unter neuer ID wiederholen.

| `action` | Weitere Eingabe | Bedeutung |
| --- | --- | --- |
| `import` | `data.source` mit optionalen Ziel-`thread_id`/`node_id`, oder ausschließlich `data.manifest` | Aktuelle freigegebene Originalbytes als geprüfte CAS-Kopie übernehmen. Der explizite Quellordner wird für die automatische Nachführung registriert. |
| `resume` | dieselbe Import-`operation_id` | Vorhandenen Job fortsetzen. Bereits gespeicherte Quittungen werden abgeglichen. |
| `reindex` | `operation_id` | Graphprojektion und Suchindex aus den kanonischen gespeicherten Daten aktualisieren; kein zweiter Import von Originalen. |
| `refresh_sources` | `operation_id` | Höchstens einen geänderten registrierten Ordner abgleichen; Status und Ergebnisbeleg getrennt lesen. |
| `rename` | `id`, `expected_revision`, `data.filename` | Anzeigename/logischen Pfad ändern, Ursprung und CAS-Inhalt erhalten. |
| `copy` | `id`, `expected_revision`, `data` mit optionalem `filename`, `folder`, `thread_id`, `node_ids` | Neuer logischer Record mit eigener ID und gemeinsam genutzten geprüften Bytes. Ohne Namen entsteht ein konfliktfreier Kopiename. |
| `move` | `id`, `expected_revision`, `data.folder`, optional bestätigte Zielzuordnungen | Innerhalb der logischen Bibliotheksordner verschieben, keine Originaldatei auf dem Mac bewegen. |
| `assign` | `id`, `expected_revision`, `data.thread_id` und/oder `data.node_ids` | Bestehende exakte Thread-/Knoten-IDs zuordnen. Mehrere Anhänge pro Knoten und mehrere Knoten je Datei sind möglich. |
| `trash` | `id`, `expected_revision`, `data:{}` | Reversibel aus normalen Ansichten/Suche ausblenden. Die gespeicherten Bytes und Referenzen bleiben erhalten. |
| `restore` | `id`, `expected_revision`, `data.trash_generation` | Dieselbe Datei-ID und Beziehungen wiederherstellen; alte Generation oder Zielkonflikt wird abgewiesen. |
| `open` | `id`, `expected_revision`, `operation_id` | Bewusst im aufgelösten Mac-Standardprogramm öffnen; keine automatische Aktion beim ersten Dateiklick. |

Für `refresh_sources` wird ein abgeschlossenes Pollergebnis dauerhaft gespeichert und bei identischer Wiederholung mit `duplicate=true` zurückgegeben. `operation` liefert denselben gespeicherten Beleg. Ein bereits gebundener Auftrag ohne definitiven Beleg bleibt `unknown` und wird nicht blind erneut ausgeführt. Das äußere `status=complete` bestätigt hier den abgeschlossenen Pollaufruf; die einzelnen Quellen können weiterhin `partial` oder `unavailable` sein. Ihre Zustände und letzten Erfolge bleiben deshalb getrennt sichtbar.

`folder` ist ein relativer logischer Bibliothekspfad, zum Beispiel `Eingang/Recherche`; `""` bezeichnet die Bibliothekswurzel. Absolute Ziele, `..`, Pfadseparatoren im Dateinamen und unbekannte Aktionsfelder werden abgewiesen. Copy/Move ändern keine fremden Originale. Ein endgültiger Lösch-/Purge-Befehl ist in diesem aktuellen Bibliotheksvertrag nicht angeboten.

Beispiele mit Platzhalter-IDs; vor einer Mutation tatsächliche `info`-Revision verwenden:

```sh
td library --request '{"action":"status"}'
td library --request '{"action":"search","query":"Brueckenplan","entity_type":"all","limit":20}'
td library --request '{"action":"list","node_id":"0123456789ab","sort":"name","limit":50}'
td library --request '{"action":"preview","id":"abcdef012345"}'
td library --request '{"action":"rename","id":"abcdef012345","operation_id":"rename-001","expected_revision":1,"data":{"filename":"Plan.md"}}'
td library --request '{"action":"operation","operation_id":"rename-001"}'
```

Für umfangreiche Importmanifeste `--request-file` verwenden. Ein Manifest enthält `files` mit tatsächlichem lokalem `path`, ursprünglichem `original_path`, stabilem `source_ref` und gegebenenfalls `sha256`, `size`, Version und bestätigten Ziel-IDs. Ein reiner alter Datei- oder Seitenverweis liefert keine importierten Bytes. Fehlende Originale bleiben dateigenau sichtbar. Unklare Zuordnungen gehen an den zentralen Eingang „Nicht zugeordnet“.

## Vorschau und Mac-Öffnen sind verschiedene Fähigkeiten

| Formate | Inhaltsindex | Interne Vorschau | Externes Öffnen |
| --- | --- | --- | --- |
| TXT, Markdown, RST | Begrenzter Text | Text | Erlaubter zugeordneter Mac-Betrachter |
| HTML/HTM | Sicher extrahierter Text ohne Script-/Styleinhalt | Metadaten entsprechend Registry und Vorschaugrenze, kein aktives HTML | Nur nach ausdrücklicher Aktion im zulässigen Standardprogramm |
| PDF | `pypdf`-Text im begrenzten Childprozess; keine OCR, verschlüsselte/gescannte Dateien gegebenenfalls nur Metadaten | Extrahierter Text, sonst Metadaten; kein eingebetteter PDF-Skriptrenderer | Erlaubter zugeordneter Mac-Betrachter |
| DOCX, ODT, XLSX, ODS, PPTX, ODP, EPUB, RTF | Begrenzte sichere Textextraktion; Makros werden nicht ausgeführt | Extrahierter Text, keine Zusage originalgetreuen Office-/Tabellenlayouts | Erlaubter zugeordneter Mac-Betrachter |
| DOC, XLS, PPT | Dateiname/Pfad/Metadaten; kein installierter Volltextadapter | Metadaten | Erlaubter zugeordneter Mac-Betrachter |
| CSV/TSV, JSON, XML, YAML, TOML, SQL, LOG, INI/CFG | Begrenzter Text | Text, keine Daten-/Queryausführung | Explizit, soweit ein zulässiger Standardbetrachter gefunden wird |
| PY, JS, TS und weitere registrierte Quellcodes/Skripte | Begrenzter Text | Text | Standardübergabe blockiert, damit ein Interpreter nicht unbemerkt Inhalte ausführt |
| JPG/JPEG, PNG, GIF, WEBP, BMP | Name/Pfad/Metadaten; keine OCR | Bild, sofern der tatsächliche Browserdecoder den Inhalt unterstützt | Erlaubter zugeordneter Mac-Betrachter |
| TIFF/TIF, HEIC/HEIF, SVG | Name/Pfad/Metadaten | Metadaten; kein aktives Inline-SVG | Erlaubter zugeordneter Mac-Betrachter |
| MP3, WAV, FLAC, AAC, M4A, OGG, AIFF | Name/Pfad/Metadaten; keine Transkription | Audiosteuerung, abhängig von tatsächlichem Codec/Browser | Erlaubter zugeordneter Mac-Betrachter |
| MP4, MOV, WEBM, M4V | Name/Pfad/Metadaten; keine Video-/Spracherkennung | Videosteuerung, abhängig vom tatsächlichen Codec/Browser | Erlaubter zugeordneter Mac-Betrachter |
| MKV, AVI | Name/Pfad/Metadaten | Metadaten | Erlaubter zugeordneter Mac-Betrachter |
| ZIP/TAR | Begrenzte sichere Mitgliedsnamen, kein rekursiver Inhaltsimport | Metadaten | Nur ausdrückliche zulässige Standardübergabe |
| GZ/TGZ | Begrenzter Text beziehungsweise TAR-Mitgliedsnamen | Metadaten | Nur ausdrückliche zulässige Standardübergabe |
| 7Z | Name/Pfad/Metadaten; kein installierter Inhaltsadapter | Metadaten | Nur ausdrückliche zulässige Standardübergabe |
| Unbekannte Dateiendungen | Name/Pfad/Metadaten, kein Inhalt geraten | Metadaten | Blockiert |

Alle aufgenommenen Dateien erhalten Metadaten-/Namenssuchbarkeit, auch wenn ihr Format keinen Inhaltsadapter besitzt. Aufnahmebeschränkungen für vertrauliche Dateien, Verknüpfungen und ausführbare Installationspakete bleiben davon getrennt erhalten. Die allgemeine Registry ist keine Aufhebung dieser Importguards. Ein beschädigter Container kann einen Extraktionsfehler haben und trotzdem als Datei verwaltbar bleiben; der Fehler darf benachbarte Suchtreffer nicht blockieren.

`external_open=true` ist keine Zusage eines installierten Programms. LaunchServices ermittelt zuerst den wirklichen Handler. Fehlende oder gesperrte Handler liefern klare Fehler; Terminal, Python Launcher und Script Editor sind keine erlaubten impliziten Betrachter. Geöffnet wird eine überprüfte, benannte und schreibgeschützte temporäre CAS-Kopie, niemals die anonyme Blobdatei als ausführbarer Befehl. Ein bestätigtes `launch_requested` belegt den Öffnungsauftrag an die benannte App, nicht menschliches Lesen. `human_read_confirmed` bleibt falsch. Derselbe Operationsbeleg darf kein zweites Öffnen auslösen.

## Ressourcen, Konsistenz und automatische Nachführung

- Import: höchstens 256 MiB pro Datei, 2 GiB pro Batch und 2.000 Dateien. Originale nur lesen; Inhalt und kopierte Bytes durch Prüfsummen binden. Quelle vor/bei Veröffentlichung erneut prüfen; Konflikte und ausgenommene Dateien bleiben pro Datei sichtbar.
- Extraktion: grundsätzlich höchstens 16 MiB Eingabe und 1 Mi Zeichen Text. Große Textdateien können einen ausdrücklich begrenzten Ausschnitt liefern. Office-/EPUB-Container: höchstens 2.000 Mitglieder, 2 MiB pro gelesenem Mitglied, 8 MiB expandierter ausgewählter Daten. Keine Dateisystemextraktion oder externe Schema-/URLauflösung.
- PDF: eigener Childprozess, fünf Sekunden Außenfrist, CPU-/Adressraum-/Datengrenzen soweit vom Betriebssystem unterstützt; Zielgrenzen drei CPU-Sekunden und 512 MiB. Höchstens 200 Seiten, 4 MiB dekomprimierter Inhalt je verarbeiteter Seite und 1 Mi Zeichen Ausgabe. Fehlender Adapter, Limits, kein lesbarer Text und Parserfehler bleiben unterscheidbar. Ein Source-Test ersetzt keinen Test dieses Workers im paketierten Desktop.
- Popup: höchstens 256 Ki Zeichen Text; der Extraktionsstatus und `truncated` erklären Begrenzung. Medien werden erst für den ausgewählten geprüften Record angefordert.
- Suchprojektion: abgeleitete `library-files/content-search.sqlite3` plus kleines `index.json`-Manifest. Canonical Records/CAS und bestätigte Thread-/Graphdaten bleiben maßgeblich. Unveränderte SHA/Suffix/Blobstempel verwenden den Extraktionscache. Ein fehlgeschlagener Index kann keinen bereits gespeicherten Dateivorgang rückgängig machen.
- Nachführung: nur ausdrücklich importierte/registrierte Quellen, maximal acht Wurzeln; kein Home-/Systemcrawler. Der Hintergrundworker prüft normalerweise alle fünf Sekunden. Ein Scan ist auf 2.000 Dateien, 8.192 Einträge, 256 Verzeichnisse und 250 ms je Wurzel begrenzt. Unveränderte Quelle erzeugt keine neuen Hash-, Import- oder Indexwrites.
- Änderungsbelege: Metadatenfingerprint einschließlich Größe, mtime, ctime und Inode; jede Änderung bekommt einen dauerhaften Übergangs-/Batchbeleg. Gleicher Fehler wird 30 Sekunden zurückgestellt. `last_attempt` und `last_success` nicht gleichsetzen. Änderung während Import verhindert einen falschen aktuellen Erfolg.
- Externe Quelllöschung: fehlende Quelle/Datei melden, gespeicherte Kopie und Herkunft behalten. Kein automatischer Papierkorb-/Purge- oder Originaldateivorgang. Bei einem unvollständigen Scan findet kein vermeintlich vollständiger Import statt.

## Tatsächliche KiraBridge-Verfügbarkeit und Abnahme

Neue ThreadDesk-Readtools können erst bei aktiviertem kompatiblem dynamischem Readzugang erscheinen. Der zuletzt aus dieser Sitzung tatsächlich gelesene Katalog war deaktiviert. Der vorhandene native ThreadDesk-Schreibadapter erlaubt nicht automatisch die neuen Libraryaktionen. Deshalb ist für diese Aktionen der bereits vorhandene autorisierte **sichtbare Terminal-/CLI-Weg** getrennt nachzuweisen; KiraBridge selbst wird nicht geändert.

Ein verfügbarer CLI-Prozess oder lokaler Test ist noch kein Bridgebeleg. Ein echter End-to-End-Nachweis bindet Quelle, Workspace, Quell-/Paketpin, tatsächliche Bridge-Identität, sichtbares freies Ziel, vollständige Ergebnisse und unabhängige Readbacks. Die hier zuvor tatsächlich gemeldete Identität war `codex`; das beweist **keine ChatGPT-Principal-Abnahme**. Ein Fixturebericht mit absichtlich offenem Identitätsfeld darf diese Lücke nicht ersetzen. Ein erneuter Bridgeauftrag für den 275-Einträge-Lauf war bei diesem Dokumentationsabgleich bereits vor nachgewiesenem Prozessstart durch einen Terminaltimeout offen. Er wird weder als gestartet noch als erfolgreich importiert gezählt; zuerst sind Task-/Terminalstatus abzugleichen, bevor eine erneute Zustellung erwogen wird.

Der vollständige Abnahmelauf lautet: Originalbytes importieren → automatische Indexierung → Namens- und Inhaltssuche → richtigen Graphknoten wählen → Popup → bewusst im nachgewiesenen Mac-Programm öffnen → umbenennen/verschieben → aktualisierte Suche/Zuordnung → Papierkorb → Wiederherstellung unter derselben ID → erneut finden. Konflikt, unbekanntes Format, fehlender Handler, große Datei, Offlinezustand und Neustart werden separat belegt. `scripts/check_library_workflow.py` erzeugt dafür eigene synthetische Daten und Originalerhaltbelege; es ist kein Import der Nutzerbibliothek und ersetzt weder die Browserbedienprüfung noch die Principalprüfung.

## Frühere Inventur und derzeit belegter Quellenzugang

Die historische Inventur enthält 275 Einträge und meldet 23 Ordner. Sie hat für die normalen Originale keinen erwarteten SHA-256 oder individuelle historische Sourceversion. Die 23 Ordner lassen sich aus den enthaltenen Dateipfaden allein nicht vollständig verifizieren. Das damalige Exportverzeichnis enthält keine Originalbytes.

Der getrennte aktuelle Quellenabgleich erfasste 24 tatsächlich lesbare gleichnamige/größengleiche lokale Kandidaten mit berechneten aktuellen Prüfsummen, fünf Größenkonflikte, 238 im geprüften Umfang nicht verfügbare Originale und acht bereits im Inventar geschützte Ausschlüsse. Summe: 275. Gleicher Name und gleiche Größe beweisen ohne alten Vergleichshash keine historische Originalidentität. Diese Zahlen belegen Zugänglichkeit/Konfliktstatus; sie sind **keine Erfolgsmeldung eines produktiven 275-Dateien-Imports**.

Die sieben alten Projekt-/Threadziel-IDs existieren im vorhandenen Operatorprofil, nicht im separaten Desktopprofil. Sie dürfen nicht nach ähnlichen Titeln still ersetzt werden. Bei einer Übernahme in das Desktopprofil ist ein bestätigtes neues Mapping oder der zentrale Eingang erforderlich. Private Pfad-/Prüfsummenlisten und geschützte Inhalte gehören nicht ungeprüft in öffentliche Belege.

Für jede Funktion sind Implementierung, passende Tests, tatsächlicher Bridgezugang sowie Installation/Produktivdatenübernahme getrennte Zustände. Der finale Integrations-/Paketbericht muss diese Zustände am tatsächlichen Quellpin ergänzen; dieses Vertragsdokument erfindet sie nicht.

Nachtrag zur Bridge-Abnahme: Der separate Auftrag `td-library-frozen-live-20261026-v2` wurde anschließend erfolgreich im sichtbaren Terminal unter `codex` ausgeführt: 275 synthetische Dateien, 51 Aufrufe des gefrorenen Backends vom Pin `387a2eb`, max. 10.530 Bytes je Antwort, automatische Quellenänderungen und unabhängige Readbacks. Completion wurde verarbeitet und quittiert. Dieser Kandidatenbeleg ersetzt weiterhin weder produktiven Originalimport noch ChatGPT-Principal- oder finale Installationsprüfung.

KEY-Aufnahmegrenze: `.key` kollidiert mit der bestehenden Schutzregel für private Schlüssel und wird im Ordnerimport sowie Dateiempfang derzeit mit `secret_name` gesperrt. Der Formatkatalog weist deshalb `import_allowed=false` aus. Ein bereits gespeicherter zulässiger Record kann verwaltbar sein; dies ist keine Zusage, eine neue Keynote-Datei aufnehmen zu können. Eine sichere positive Keynote-Inhaltsprüfung einschließlich echter geprüfter Fixture fehlt. KEY gilt ausdrücklich als noch nicht vollständig unterstützt; die private-Schlüssel-Sperre wird nicht pauschal gelockert.
