# ThreadDesk – Abschlussplan, 2. Oktober 2026

## Ziel und Geltungsbereich

Ein verständlicher lokaler Arbeitsplatz, der Kontext und Arbeitsstand zwischen
Mensch und KI erhält. Kein zweiter externer Orchestrator. Der lokale Hausmeister
bleibt ein gesonderter, optionaler Akteur innerhalb seiner dokumentierten Grenzen.

Dieser Plan ersetzt den überholten Vier-Funktionen-MVP-Plan vom 14. August.
Code und aktuelle Abnahme: **PR #62**, Branch `feat/desktop-brand-icons`.
Konkrete Testzahlen und Build-Links stehen im PR, nicht in parallel gepflegten Kopien.

## Abschlussreihenfolge

1. Vorhandene Funktionen und gesamten Branch prüfen; keine funktionierenden Module neu bauen.
2. Team-Sync mit zwei echten Serverprozessen und echter Browserbedienung für JSON und SQLite abnehmen.
3. Private Notizen von freigegebenen Einträgen trennen; Raum, Gegenstelle und Schreibrolle prüfen.
4. Offline-/Neustartverhalten, Konflikterhalt und wiederholten Sync ohne Kopien nachweisen.
5. Lokale Oberfläche ohne CDN laden; App-Start und Datenerhalt absichern.
6. Windows-, Intel-Mac- und Apple-Silicon-Pakete mit bestehender Bildmarke bauen und ihre Selbsttests ausführen.
7. README aktualisieren, Quellen/Prüfsummen beilegen, ganze Testsuite zweimal ohne übersprungene Abnahmetests ausführen.
8. Ergebnis anhand des konkreten Commit-Standes dokumentieren. Keine automatische Veröffentlichung oder Übernahme nach main.

## Technische Grundsätze bleiben erhalten

Core, Storage, UI, Services und API bleiben getrennt. UI und Speicherung sind
austauschbar. Neue fachliche Funktionen gehören in ihre eigenen Module.
Code, Beispielmaterial und personenbezogene Arbeitsdaten bleiben getrennt.
Testdaten sind synthetisch und liegen ausschließlich in temporären Arbeitsbereichen.

## Reproduzierbare Prüfung

```sh
python -m pip install -e '.[dev,ui,browser]'
python -m playwright install chromium
python scripts/check_release_inputs.py
python -m pytest -q -ra
python -m pytest -q -ra
```

Für einen nativen Build auf der jeweiligen Plattform zuerst die Icons erzeugen
(`python -m pip install CairoSVG Pillow`, `python scripts/build_icons.py`), dann
`python -m pip install -e '.[ui,desktop]' pyinstaller` und
`pyinstaller --noconfirm --clean packaging/ThreadDesk.spec` ausführen.
Die GitHub-Builds erzeugen passende EXE-/DMG-Pakete sowie `.sha256` und `.build.json`.
Das macOS-Paket wird nur ad-hoc signiert, nicht als Apple-notarisiert ausgegeben.

## Nicht durch lokale CI bewiesen

- Start und Bedienung auf Daniels tatsächlichem Intel-Mac und seiner macOS-Version.
- Qualität, Antwortzeit und Ressourcenverbrauch des ausgewählten lokalen LLM mit echten Projektdaten.
- Produktiver Notion-Import; Notion bleibt bei dieser Arbeit unangetastet.
- Zusammenarbeit über einen externen Server, mehrere Haushalte oder eine öffentliche Server-Oberfläche.
- Native Linux- und Mobilpakete.

Diese Punkte bleiben offen und dürfen nicht aus grünen lokalen Tests als erledigt
abgeleitet werden. Der lokale HTTP-Sync ist keine Ende-zu-Ende-Verschlüsselung.
Der frühere Wunsch nach einem Wechsel zwischen 5–10 Threads in unter zwei Sekunden
bleibt ein Nutzerziel, keine ungeprüfte Leistungsbehauptung.

## Umsetzung der Nutzbarkeits-Abnahme, 2. Oktober 2026

PR #62 ist inzwischen nach `main` gemergt. Die nächste Ausgabe ergänzt eine
bedienbare Datenseite mit herunterladbaren, geprüften Sicherungen für JSON und
SQLite. Wiederherstellung öffnet einen getrennten Arbeitsbereich; das Original
bleibt erhalten. Die Auswahl bleibt über Neustarts erhalten und gilt für Desktop,
CLI und MCP. Die lokale Desktop-Adresse und Start-Sperre bleiben an die
Installation gebunden.

Die vom Nutzer beauftragte Auslieferung ersetzt die frühere Beschränkung auf
unveröffentlichte Build-Artefakte: Eine neue Versionsnummer wird als Release-Kandidat
veröffentlicht, sobald alle drei nativen Builds und die vollständige Testsuite
zweimal ohne Fehler oder übersprungene Tests durchgelaufen sind. Vor dem Upload
werden Dateien, Plattform, Architektur, Commit, Größe und Prüfsumme geprüft.
Bereits veröffentlichte Versionen werden nicht ersetzt.

Externe Agenten werden weiterhin über vorbereitete Übergaben angebunden. Die
lokale KI benötigt ein vom Nutzer ausgewähltes und vorhandenes Ollama-Modell.
Internet-Teamhosting bleibt außerhalb dieser lokalen Ausgabe.

## Gesamtauftrag E01–E09, 20. Oktober 2026

Dieser Abschnitt führt den bestehenden Plan fort. Die aktuelle ausdrückliche
Beauftragung geht älteren Übergabeformulierungen vor; historische Nachweise
bleiben datiert erhalten. Vollständiger Originalplan: ThreadDesk-Thread
`6b5b73b9de36`, „Gesamtplan ThreadDesk & 4AllPass – 20.10.2026“, Revision 3.
Zehn geordnete Bridge-Anlagen ergeben 107935 UTF-8-Bytes, SHA256
`4b8ac493add0b76bd1a353d59d13152bbb5ec62bc956c1def9f1ccc1aa211ca8`.
Die vollständige Fach-API-Nachlese stimmt bytegenau überein. Im Thread steht
der erste Originalteil in der markierten Beschreibung, der Rest in den
Notizen; beide werden ohne zusätzliches Trennzeichen aneinandergefügt.
Gespräch `kira-gesamtplan-team-20261020-1031` und quittierte Übergabe
`7a7a268e-09c2-4a0f-a333-031cd7fc094c` gehören zum selben Auftrag. Ihre
Übernahme löst keinen zweiten CLI-Auftrag aus und bedeutet keine Fachabnahme.

Codex koordiniert und implementiert mit abgegrenzten nativen Teamaufgaben;
Grok prüft konkrete Commits unabhängig über sein zugeordnetes bestehendes
sichtbares Fenster. Groks nativer `spawn_subagent`-Modus ist praktisch belegt;
für RC11 startete er zwei abgegrenzte Prüfaufträge. Ihre Einzelresultate stehen
noch aus; Groks eigene unabhängige RC11-Prüfung ist bereits eingegangen. Kein Codex-Unteragent ersetzt diese unabhängige Prüfung. Neue
Hauptsitzungen oder ein Hintergrundersatz sind nicht vorgesehen. Änderungen
an gemeinsamen Dateien werden vorab eindeutig einem Bearbeiter zugeteilt.

| ID | Umfang / bestehende Zuordnung | Stand und nächster Schritt |
| --- | --- | --- |
| E01.1 | P00/R01, Quell-/Paket-/Arbeitsbestand | Aktuelle Bestandsaufnahme: ThreadDesk main `b366552` (TD01), 4AllPass main `262917f` (AP01/AP02); fremde schmutzige Hauptcheckouts erhalten. Vorhandene M1/M2/Wissens-/Design-/RC3-Belege bleiben ihrem Quellstand zugeordnet. Vollständige Claim-/Prüfzuordnung bleibt offen. |
| E01.2 | RC9/RC10, ST-01–ST-05 | Bridge-Reparatur abgeschlossen übernommen: Code `956b0f8`, Architektur `41f4b89`, aktiver Quellpin `cfad2a30…ceb7`; 941 Mac-Gesamttests. Echter Kira→sichtbares Original-Codex→Kira-Weg mit getrenntem Einfügen/Return, Codex-ACK, Rückantwort und tatsächlichem Kira-Connector-ACK belegt. Originaltest nicht wiederholt. Siehe KiraBridge `docs/evidence/receiver-resilience-mac-20261020.json`. |
| E01.3 | Native Teams und verbindliche Übergaben | Codex führt drei abgegrenzte native Teamaufgaben. Grok hat die vorhandenen E02-Aufträge authentisiert empfangen und selbst unabhängig geprüft; sechs native Teilreviews tatsächlich gestartet, Einzelresultate werden abgeholt. Bestehende sichtbare Hauptsitzungen erhalten, kein Ersatzagent. |
| E02.1 | TD-01, F1/F2 | Abgeschlossen im Quellumfang: PR #78 (`2fafc6a`) als `b366552` integriert. Native Windows164, Ubuntu814 zweimal, drei native Installer-Selbsttests grün. Grok `ship` mit eigenen 175 Mac-Tests, Ergebnis `3c004034-0e3d-4dea-8811-18d66aa0a24a`. Keine Live-Installation; JSON-UNC bleibt nativ unbestätigt, UNC-Backup ausdrücklich gesperrt. |
| E02.2 | TD-02 | Aktueller Reviewpin `129a42e`: Windows164, Ubuntu861 zweimal ohne Skips, drei Installer gebaut/selbstgeprüft. Grok `ship`, Ergebnis `71d17409-3db3-4212-9923-45c2483776d2`; eigener gezielter Lauf zunächst fehlendes Browserbinary, betroffener Fall mit vorhandenem Chrome danach bestanden. Echte WKWebView-Abnahme JSON8/8 + SQLite8/8; WLAN-Socketvertrag am selben Host11/11. Physischer zweiter LAN-Client fehlt. Auf TD01-main ohne Laufzeitänderung neu aufgesetzt, frische CI/Integration folgen. |
| E02.3–4 | AP-01/AP-02/F4 | Quellumfänge abgeschlossen: AP01 PR #229 (`ab1aba3`) als `7a9416d`, AP02 PR #230 als `262917f` auf main; jeweils grüne PR-CI. Grok `ship` beider Umfänge, Ergebnis `9784c6e6-3258-42ad-8295-a30ea114ee27`, eigener Body-Lauf11/11. SQLite156+1 expliziter Skip; echter Postgres-CI-Lauf157 bestanden. Kein neues 4AllPass-Paket daraus abgeleitet. |
| E03 | P01–P05, R02–R07/R12, AP-04 | Offen: Kryptografie, Snapshot, Konto/Sitzung, Geräte, Recovery und belastbarer Identitätsvertrag. Vorhandene Tests ersetzen keine Bereichsabnahme. |
| E04 | P06–P08/P11–P12, R08–R11/R15–R17, AP-03 | Offen: Browser-/Desktop-/native Nutzerwege und Paketnachweise am tatsächlichen Kandidaten. |
| E05 | UI-01, zugehöriger TD-08-Umfang | Offen: gemeinsame kompakte App-Leiste, vorhandene Icons, bestätigte frische Verbindungen; nur 4AllPass bei bestätigtem Unlock sehr dezenter Puls. |
| E06 | TD-03–TD-06/TD-08, AP-04 | Offen: Projektrollen, atomarer Transfer, Team-Sync, projekt-/thread-/revisions-/laufgebundene Agentenaufträge. |
| E07 | AP-05–AP-07, P09/R13–R14 | Offen: begrenzte Freigaben, tatsächliche Hostgrenze und genau eine freigegebene reale Anbieteroperation; kein synthetischer Test als Produktionsbeweis. |
| E08 | TD-07 | E08.1 in Prüfung: optionaler lokaler Titel-/Beschreibung-/Notizschnitt mit FTS5, begrenztem JSON-/No-FTS-Ersatz und `td search` auf main `88a5b4d`; default aus, expliziter Aufbau, ehrlicher Teilstand und frische lokale Policy. [Vertrag und Grenzen](LOCAL-SEARCH.md), [Quell-/Test-/Messnachweis](evidence/e08-local-search-20261020/STATUS.md). Echte 10k-/100k-Textmessung und unabhängige Abnahme werden getrennt nachgeführt. Projekt-/Teamrechte bleiben E06; optionaler Bridge-Dateiindex und Produktfreigabe weiter offen. |
| E09 | TD-09/AP-08, P10–P12, R01–R17, H1–H6, T01–T22 | Offen: einschlägige Nachweise zuordnen, Nutzer-/Modulwege abnehmen, geprüfte Pakete nach bestehenden Release-Gates ausliefern. |

Aktueller Fortsetzungsauftrag: `channel-958719a7a05448739bcdf8d217f6d493`,
Nachricht `51ade15c-4acb-494f-8cf0-d4035786f6c0`, authentisiert quittiert.
Der vorhandene Planthread enthält den Wiedereinstieg ab Revision4; seine
Originalbeschreibung und Originalnotizen bleiben unverändert. Die frühere
Mac-Sperre und damalige unbekannte Testlage sind überholt: Der Originaltest
ist abgeschlossen, die zusätzliche einmalige Sitzungskontrolle ebenfalls.
Keiner dieser Aufträge wird erneut ausgeführt. Andere ungeklärte historische
Übergaben bleiben ohne neue Eingabe erhalten. Der öffentliche Handy-/Tunnelweg
ist auf Daniels Wunsch zurückgestellt und wird hierbei nicht verändert.
Restrolle nach Leitungstransfer, genaue Manager-/Abnahmerechte, Stellvertretung
sowie Executor-Betriebsprofil/erste reale Operation benötigen vor dem jeweiligen
Ausbau eine fachliche Entscheidung; sie blockieren lokale Reparaturen nicht.

Jeder folgende Unterpunkt ergänzt hier Commit, Dateien, konkrete Tests,
unabhängiges Grok-Urteil, verbleibende Grenze und nächsten Schritt. Status bleiben
offen / in Arbeit / in Prüfung / blockiert mit Ursache / abgeschlossen im benannten
Umfang. Paketbau, Installation, Aktivierung und Produktfreigabe sind eigene Belege.

### E02 / TD-01: erster nativer Gegenbefund

Draft-PR #78, Ausgangskandidat `3284d4b`: macOS-Integration 170 bestanden.
Der tatsächliche Windows-Lauf 39409334308 meldete dagegen 90 bestanden und
69 fehlgeschlagen, keinen Skip. Ursachen: plattformabhängige Backslashes in
Manifestnamen, ein von Windows abgewiesener WAL-Umbenennungsaufruf (Fehler87)
und eine Keywordkollision in zwei Windows-Testparametrisierungen. Die enge
Korrektur verwendet POSIX-Manifestnamen und einen dokumentierten nativen
Same-directory-Rename des geöffneten Tempdateihandles. Neue Regressionen
prüfen verschachtelte Artefakte sowie Journal-Ersetzen/Recovery/Löschen.
Nach der Korrektur sind 119 betroffene Mac-Fälle grün; der neue native Lauf
und Groks Urteil bleiben offen. Der erste fehlgeschlagene Lauf bleibt erhalten.
Ein separater Apple-Silicon-Installerlauf scheiterte bei der DMG-Erstellung
mit `hdiutil: Resource busy`; daraus folgt weder ein fertiges DMG noch ein
Fehlernachweis im Backup-Code. Keine Live-Installation dieses Kandidaten.

Der Folgelauf `2b62285` bestätigt nativ 25 Source-Adapter- und 17
JSON-Controlfälle; insgesamt Windows158 bestanden/3 fehlgeschlagen,
Ubuntu810 bestanden/1 fehlgeschlagen. Die Installer dieses Pins wurden
auf allen drei Plattformen erfolgreich gebaut und selbstgeprüft; das ist
keine Gesamtabnahme der noch fehlerhaften Quelle und keine Veröffentlichung.
Die verbliebene Fachfehler-Umdeutung ist im nächsten kleinen Diff korrigiert.
Die Windows-Gegenproben prüfen nun den echten ENOSPC-Cause statt dessen
Textdarstellung sowie eine tatsächlich verweigerte Umbenennung getrennt
vom erfolgreichen Austausch mit Fremddaten-Erhalt. Eine Verweigerung
belegt dabei allein noch nicht die Ursache. Codex-interne Gegenprüfung
bestätigt diese Testgrenze; 31 betroffene Mac-Fälle grün, nativer neuer
Gesamtlauf und Grok weiter offen.

E03-Vorbereitung ergänzt die Bestandsmatrix um neue Bibliotheksbelege:
321 Kryptofälle mit `RUN_HEAVY=1` und 26 WebAuthn-Bibliotheksfälle bestanden,
keine Skips. Synthetische Vektoren/FakeAuthenticator sind keine Hardware-,
Browser-, Personen-/Geräte- oder E03-Gesamtabnahme. Keine E03-Funktion
vor Abschluss der E02-Reparaturen freigegeben.


### E02 / TD-02: kombinierter Prüfkandidat

Die lokale HTTP-Grenze und schreibfreie GET-Ansichten sind auf die TD01-Reparatur
aufgesetzt. Der bisherige rohe TestClient des Backup-UI-Tests verwendet jetzt
auch den echten Sitzungs-/CSRF-Bootstrap; es gibt keinen Allowall-Testschalter.
Codex-interne Gegenprüfung fand und korrigierte Actor-/Modulinitialisierung beim
GET. Expliziter App-/Profilstart erhält bestehende IDs/Freigaben. Modellstatus
ist zeitlich begrenzt und läuft auch in offenen Seiten nach 30 Sekunden sichtbar
auf ungeprüft ab, ohne GET-Netzwerk/Modellstart. Drei exakte Room-Maschinenwege
behalten ihre eigenen Tokens; keine bestätigte Person wird daraus abgeleitet.
Echte Browser- und Zwei-Prozess-Fälle wurden vor Integration geprüft; die neue
kombinierte Quelle benötigt jetzt ihre eigene Prüfung und Groks Abnahme.
Keine produktive Profil-, Peer-, Installations- oder Tunneländerung.

Der TD01-Pin `2fafc6a` hat anschließend den nativen Windows-Lauf mit 164
bestandenen Fällen und die vollständige Ubuntu-Suite zweimal mit jeweils 814
bestandenen Fällen erreicht, ohne Fehler oder Skips. Alle drei Installer wurden
gebaut und selbstgeprüft; Groks unabhängige TD01-Abnahme steht noch aus.

Der kombinierte TD02-Pin `c25bf76` besteht Windows mit 164 Fällen und den
Installerbau auf allen drei Plattformen. Ubuntu meldet dagegen 835 bestanden,
14 fehlgeschlagen und keine Skips: elf Navigationstimeouts, zwei nachgewiesene
DE/EN-Abweichungen nach erfolgreichem Speichern und eine fehlende Übersetzung.
Die zweite Gesamtrunde lief nach diesem Fehler nicht. Die Abweichung ist eng
korrigiert: Ansichtskontext wird für Teilansichten und normale Formulare erhalten,
gespeicherte Sprach-/Registerpräferenzen gewinnen; GET speichert keine Präferenz.
128 betroffene Fälle einschließlich echter en-US-Browser mit JSON/SQLite bestehen.

Die Navigationstimeouts sind noch nicht erklärt. Zwei isolierte lokale
Prozessprüfungen, davon eine mit dem exakten bisherigen Pin und den CI-Versionen
von Browser/Server, reproduzieren sie nicht. Ein nur in pytest ausdrücklich
aktivierter Recorder erfasst beim ursprünglichen Timeout begrenzte Anfragezustände
und lokale Python-Stacks vor dem Aufräumen. Er ändert weder Wartezeiten noch
Ergebnisse, wiederholt nichts und liest keine Header, Inhalte oder URL-Werte.
Nicht verfügbare Kindprozess-Stacks/Pipefüllstände werden ausdrücklich so benannt.
Ubuntu prüft zunächst genau den ersten fehlgeschlagenen Fall und dann weiterhin
die vollständige Suite zweimal mit unveränderter Fehler-/Skip-Abnahme. Der neue
Linux-Nachweis und Groks Prüfung bleiben bis zu ihren tatsächlichen Ergebnissen offen.

Der instrumentierte Pin `c059b81` liefert den konkreten Befund: Ubuntu 844
bestanden/16 fehlgeschlagen, keine Skips, alle Fehler ursprüngliche
30-Sekunden-Navigationstimeouts. Alle 16 Aufnahmen zeigen ausschließlich je zwei
offene `POST /hausmeister/activity` mit HTTP 200; HTML und Static-Dateien sind
abgeschlossen. Die Sprach-/Übersetzungsfälle bestehen. Der Browser verwirft den
kleinen Fetch-Antwortbody, während der neue HTTP-Guard `no-store` setzt. Der
versionsgenaue [Chromium-156-Quellpfad](https://chromium.googlesource.com/chromium/src/+/refs/tags/156.0.8078.4/third_party/blink/renderer/core/fetch/fetch_manager.cc#820)
liest solche Antworten nicht automatisch leer. HTTP 200 allein ist kein
Anfrageabschluss. Ein neuer echter Browsergegenfall reproduziert denselben
30-Sekunden-Fehler lokal, ohne Fetch-Mock oder Bodykonsum aus dem Test.

Die enge Korrektur konsumiert ausschließlich die kleine Activity-Antwort im
bestehenden Promise. `keepalive`, `no-store`, Drosselung, Nutzdaten, Origin und
CSRF bleiben erhalten; es gibt keinen Retry. Derselbe Gegenfall, Hausmeister-
Fälle und der ursprüngliche Layoutfall bestehen danach zusammen mit 40 Fällen.
Ein getrennter Chromium-156-A/B-Lauf bestätigt bei identischem Server und
DOMContentLoaded-Eingaben: Original nach 30,003 Sekunden gesperrt, nur mit
Bodykonsum Navigation nach 0,651 Sekunden erfolgreich; beide Activity-Antworten
einschließlich der nach 15 Sekunden folgenden Meldung vollständig abgeschlossen.
Die CI prüft zuerst diesen Gegenfall und den bisherigen Layoutfall; die beiden
vollständigen Gesamtläufe und ihre ursprünglichen Fehler-/Skipregeln bleiben
verbindlich. Der vorherige fehlgeschlagene Lauf bleibt als Beleg erhalten.
Neuer Linux-Pin und tatsächliches Grok-Review bleiben offen, bis sie vorliegen.

### E02 – aktuelle Abnahme und Fortsetzung (20.10.2026, nach 16:23)

Die vorstehenden Zwischenläufe bleiben historische Fehler- und Korrekturbelege.
Der abschließende TD02-Pin `129a42e` besteht CI-Run `39418788437`:
Windows164 und Ubuntu861 zweimal, ohne Fehler oder Skips. Installer-Run
`39418788426` baut und prüft Windows, Intel-Mac und Apple-Silicon-Mac.
Groks unabhängiges `ship` gilt genau diesem Pin; der alte Pin `c25bf76`
ist nicht freigegeben. Beim Neuaufsetzen auf den squash-integrierten TD01-main
sind `src`, `tests`, `pyproject.toml` und `.github` bytegleich geblieben.

Codex-Unteragent `td_e02_inventory` prüfte zusätzlich das echte WKWebView
auf Intel/macOS15.7.4, pywebview6.2.1, mit unverändertem Cocoa-Adapter:
JSON8/8 und SQLite8/8 Prüfgruppen. Temporäre Foundation-Homes, Browserprofile,
Daten und Modell-Fixture sind belegt; vorhandene Dienste wurden erhalten.
Elf weitere Fälle prüfen echte TCP-Tupel über die eigene WLAN-Adresse.
Das ist ein Same-host-Transportnachweis und keine Zwei-Geräte-LAN-Abnahme;
es fehlt ein zugeordneter kontrollierbarer zweiter Client. Private Einzelbelege:
`~/.config/kirabridge/repairs/gesamtplan-fortsetzung-20261020-1623/td02-native-lan-129a42e/FINAL-RESULT.json`.

Nächste unabhängige Arbeit: E03-IndexedDB-Commit/Abort und H1-Kontoregistrierung
in getrennten bestehenden 4AllPass-Worktrees; Grok spezifiziert AP04 und holt
vorhandene native Reviewresultate ab. E08/TD07 wird als lokales optionales
Suchmodul vorbereitet. E03–E09 sind damit nicht insgesamt abgeschlossen.
