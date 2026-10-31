# ThreadDesk: usage and developer reference

Detailed material moved from the README on 31 October 2026. Source features described here are not automatically included in the published desktop v0.1.1rc1. For the current download and a short introduction, see [English](../README.md) or [Deutsch](../README.de.md).

## Bibliothek importieren / Import a library

**Deutsch:** Unter „Daten“ gibt es „Bibliothek importieren“. ThreadDesk übernimmt damit vollständige Dateien aus einem Ordner auf diesem Mac, aus einer Dateiauswahl oder aus einem ZIP-Export. ChatGPT bietet dieser Anwendung keine Bibliotheks-API. Die Originale werden nur gelesen und bleiben unverändert. Kopien liegen unter `library-files/` im lokalen ThreadDesk-Ordner (`THREADDESK_HOME`, sonst `~/.threaddesk`): der Inhalt adressiert mit SHA-256 unter `blobs/`, die Herkunft unter `records/`. Ein Ordnername, der einem vorhandenen Thread-Titel entspricht, ordnet die Datei diesem Thread zu. Ohne Treffer entsteht der Thread „Nicht zugeordnet“. Dieselbe Prüfsumme wird nicht doppelt gespeichert. Eine spätere andere Prüfsumme am selben Herkunftspfad wird eine weitere Version; die ältere bleibt. Geheimnisartige Dateinamen und Schlüssel in Textdateien werden nicht gespeichert. ZIP-Pfade mit `..` werden abgewiesen. Grenzen auf diesem Rechner: 2000 Dateien, 256 MiB je Datei, 2 GiB je Lauf. Erst eine bestandene zweite Prüfsumme gilt als gespeichert. Unterbrochene Läufe setzt derselbe Ordner über „Fortsetzen“ fort. Die Datei lässt sich danach in ThreadDesk öffnen.

**English:** Data includes “Import a library”. ThreadDesk then copies complete files from a folder on this Mac, a file selection, or a ZIP export. ChatGPT does not offer this application a library API. Originals are only read and stay unchanged. Copies live in `library-files/` inside the local ThreadDesk directory (`THREADDESK_HOME`, otherwise `~/.threaddesk`): content is addressed by SHA-256 under `blobs/`, and origin metadata under `records/`. A folder name that matches an existing thread title assigns the file to that thread. Otherwise the thread “Nicht zugeordnet” is used. The same checksum is not stored twice. A later different checksum for the same origin path becomes another version; the older one remains. Secret-like filenames and keys inside text files are not stored. ZIP paths containing `..` are rejected. Limits on this machine: 2000 files, 256 MiB each, 2 GiB per run. A file counts as stored only after a second checksum succeeds. The same folder resumes an interrupted run. The file can then be opened inside ThreadDesk.

Supported formats / Unterstützte Formate: Markdown, text, CSV, JSON, YAML, HTML, XML, PDF, Word, Excel, PowerPoint, OpenDocument, RTF, PNG, JPEG, GIF, WebP, HEIC, TIFF, BMP, SVG, ZIP, MP3, WAV, M4A, AAC, OGG, FLAC, AIFF, MP4, MOV, WebM, MKV.

**Deutsch:** Nach der Übernahme baut ThreadDesk einen lokalen Index aus Metadaten und, bei Textformaten, einem Auszug. PDF, Office, Bilder, Audio und Video sind über Namen und Herkunft suchbar, nicht über den Binärinhalt. Aufträge heißen `finde`, `öffne` und `ordne … zu`. `öffne` öffnet die gespeicherte Kopie. Die Taste „Sprechen“ nutzt die Spracherkennung des Browsers, wenn er sie auf `http://127.0.0.1` anbietet. KiraBridge hat dafür keine eigene Operation und wird von diesem Modul nicht aufgerufen.

**English:** After a copy, ThreadDesk builds a local index from metadata and, for text formats, an excerpt. PDF, Office, images, audio, and video are found by name and origin, not by binary content. Commands are `find`, `open`, and `organize … into`. `open` opens the stored copy. Speak uses the browser’s speech recognition when it is available on `http://127.0.0.1`. KiraBridge has no operation for this and is not called by the module.

[Übergaben / Handoffs](../docs/evidence/seven-tools-20261018/TD-C02.md) · [Fachmutationen / Managed changes](../docs/evidence/seven-tools-20261018/TD-C01.md).


### Quellstand und installierter Download / Source versus download

| Stand | Nachweis und Grenze |
| --- | --- |
| Desktop 0.1.1rc1, 02.10.2026 | Historischer veröffentlichter Download und seine damaligen Paket-/Testbelege; unverändert, keine rückwirkende Lizenz- oder Designumschreibung. |
| main-Basis `bba99b0`, 18.10.2026 | TD-C01/02 übernommen: revisionsgebundene Verwaltung und ausgestellte Handoff-/Laufbindung. |
| Diese Quelländerung TD-C03/D01/R01 | Wissensführung/Wiedereinstieg, exakter Rückgabeabruf, begrenzter neuer Wissenskontext und selektiv abgeglichene Design-PR-Teile. Gezielt isoliert geprüft, kein neuer Desktoprelease und keine Nutzerinstallation umgestellt. |

[PR #66](https://github.com/landjunge/threaddesk/pull/66) war beim Abgleich weiter
offen. Aus `43dd13a` werden vorhandene UI- und passende Testteile übernommen;
ältere Speicher-, Versions-, Lizenz- und Paketierungsstände werden nicht pauschal
zurückgemischt. Die vollständige alte PR-Kette gilt dadurch nicht als übernommen.

Published desktop 0.1.1rc1, current source and the actually configured Bridge peer
are different states. Use a matching source installation and operator-configured
MCP/Bridge permissions for the new tools. No claim of Internet team deployment,
external source verification or a newly published native package is made.

### Lokales Fenster und Neustart

Diese Quelländerung schützt Änderungen aus dem lokalen Browserfenster gegen
fremde Webseiten. Nach einem Dienstneustart die Seite einmal neu öffnen, bevor
du weiterarbeitest; ein alter Schreibauftrag wird nicht automatisch wiederholt.
Die Raumkopplung verwendet weiterhin ihre eigenen Einladungen und Gegenstellentokens.
Eine lokale Browserverbindung bestätigt keine Person oder Teamrolle.

Die Modellanzeige zeigt den Zeitpunkt ihrer letzten Prüfung. Nach 30 Sekunden
wird sie „Ungeprüft“; die gespeicherte Modellwahl bleibt erhalten. Ein Seitenaufruf
installiert keine Module und startet keine Modellprüfung. Diese Änderung ist
ein geprüfter Quellkandidat, noch kein neu installierter Desktop-Download.

### Gemeinsam arbeiten – ausdrücklich freigeben

Im Bereich **Raum** einen Namen eingeben und **Raum anlegen** wählen. Die Leitung
kann eine Einladung als **Mitglied** oder **Nur lesen** erzeugen. Auf der zweiten
Installation den Einladungscode und die lokale Adresse der ersten Installation
eintragen und **Koppeln** wählen. Die eingeblendeten Mitglieder zeigen die Kopplung.

Ein Whiteboard-Eintrag bleibt standardmäßig privat. Nur mit dem Freigabehäkchen
werden **der Eintrag einschließlich seiner Zuordnungen und der Thread-Titel**
für den ausgewählten Raum geteilt. Die separate private Thread-Notiz wird dadurch
nicht freigegeben. **Synchronisieren** stößt den Austausch bewusst an; es gibt
keine heimliche Komplettübertragung des Arbeitsbereichs.

**Nur lesen** darf empfangen, aber keine Raum-Einträge veröffentlichen. Eigene
neue Notizen bleiben privat. Ein Offline-Fehler bedeutet nicht, dass deine Daten
weg sind: Nach Rückkehr der Gegenstelle erneut synchronisieren. Bei einem
Inhaltskonflikt bleiben beide Fassungen erhalten. Wiederholter Sync darf keine
zusätzlichen Kopien erzeugen. Die Desktop-Adresse bleibt nach Neustarts gleich;
ist ihr Port belegt, erscheint ein Fehler statt einer Verbindung zu einer fremden App.

**Aktuelle Grenzen:** Die Abnahme prüft zwei getrennte lokale Serverprozesse, nicht
die Zusammenarbeit über einen Internet-Server. Die Oberfläche ist keine öffentlich
abgesicherte Server-Anwendung und darf nicht unverändert ins Internet gestellt werden.
Der lokale Austausch verwendet HTTP; er ist keine Ende-zu-Ende-Verschlüsselung.
Ein Sync-Paket ist auf 1.000.000 Bytes begrenzt. Zu große oder fehlerhafte Pakete
werden abgewiesen, nicht als erfolgreich abgeschnitten. Externer Server-Sync bleibt
ein eigener, noch abzunehmender Ausbau.

### Deine Daten sichern

Aktive Entwicklung und Abnahme laufen derzeit für Linux und macOS. Windows ist
auf Nutzerentscheidung vorübergehend pausiert; vorhandene Windows-Downloads
bleiben erhalten. Die automatische Veröffentlichung einer neuen gemeinsamen
Drei-Plattform-Ausgabe ist solange ausgesetzt.

Oben **Daten** öffnen und **Sicherung herunterladen** wählen. Die ZIP-Datei enthält
Threads, Notizen, Zwischenstände, Wissenskarte, Whiteboards und lokal gespeicherte
Übergaben für JSON oder SQLite. Auch importierte Bibliotheksdateien,
Empfangsbestätigungen und gespeicherte Teile angefangener Dateiübertragungen
werden gesichert. Nach Wiederherstellung können diese Übertragungen mit ihrer
bisherigen Kennung fortgesetzt werden. Verlinkte Dateien außerhalb von ThreadDesk bleiben
an ihrem ursprünglichen Ort. Der bestehende portable Backupweg verarbeitet große
Dateien blockweise über temporäre Dateien. Er umfasst auch die lokalen Ordner
`Tool-Planung`, `Workflow`, `Zukunftsvisionen`, `Bilder` und gespeicherte
Agenten-Laufzeitdaten; versteckte Daten innerhalb dieser Fachordner bleiben erhalten.

Symbolische Links in Artefakt-, Import- und Planungsordnern werden nur mit ihrer
Zielangabe im Integritätsmanifest gespeichert. Ihre Ziele werden nie verfolgt;
beim Wiederherstellen bleiben sie inerte Metadaten und werden nicht als Links
angelegt. Links an kanonischen Thread-, Datenbank- und Bibliothekspfaden bleiben
gesperrt. Leere Fachverzeichnisse werden ebenfalls wiederhergestellt. Reguläre
Quelldateien werden über gebundene Deskriptoren und erneute Hashvergleiche geprüft;
eine beobachtete Änderung bricht den Export ab. Der parallel fortgeschriebene
Pollerstatus `library-watch.json` wird ausdrücklich als geprüfter Dateistand zu
einem Zeitpunkt aufgenommen, ohne eine globale Transaktion aller Dienste zu behaupten.

Die dateibasierte portable Sicherung ist standardmäßig auf 8 GiB und 200000
Einträge einschließlich Verzeichnis-/Linkmetadaten begrenzt; das Manifest darf
höchstens 32 MiB groß sein. Unkomprimierte Daten, Manifest und Archiv unterliegen
der Bytegrenze. Überschreitungen führen zu einer Fehlermeldung; Dateien werden
nicht zum Einhalten der Grenze ausgelassen. Das portable Format v3 benötigt den
aktuellen Leser; bestehende v1/v2-Sicherungen bleiben lesbar. Der ältere
Bytes-Hilfsaufruf ist weiterhin auf 128 MiB begrenzt, während Oberfläche und
Fachbefehle den dateibasierten Streamingweg verwenden.

Zum Wiederherstellen die Sicherung auswählen, das Öffnen bestätigen und
**Sicherung öffnen** wählen. ThreadDesk prüft die Dateien und öffnet einen eigenen
Arbeitsbereich. Der bisherige Bereich bleibt erhalten. Unter **Daten** kannst du
zwischen dem Original und den wiederhergestellten Bereichen wechseln. Die Auswahl
und spätere Änderungen bleiben über Neustarts erhalten; CLI und MCP verwenden
dieselbe Auswahl. Der lokale Hausmeister bleibt nach dem Wiederherstellen aus.

Die ZIP-Datei enthält auch private Inhalte und Raum-Zugangsdaten. Bewahre sie an
einem sicheren Ort auf. Beschädigte oder zu große Sicherungen sowie zusätzliche,
nicht im Manifest geprüfte Dateien werden abgewiesen. Restore übernimmt nur die
geprüften Dateien; ein vorhandenes Ziel wird nicht ersetzt. Dateinamen müssen
auch unter Windows eindeutig sein: Gerätenamen wie `NUL` oder `CON.json`,
Laufwerks-/Datenstromangaben und abschließende Punkte oder Leerzeichen sind
unzulässig. Eine solche Quelle wird abgelehnt, statt Dateien still wegzulassen.
Wenn Namen auf dem Ziel-Dateisystem kollidieren, etwa durch Groß-/Kleinschreibung
oder Unicode-Varianten, wird ebenfalls abgebrochen. Keine Datei wird dabei durch
eine andere Datei aus derselben Sicherung überschrieben.

### Lokaler Hausmeister / Local caretaker

#### Deutsch

ThreadDesk kann einen lokalen KI-Assistenten über Ollama verwenden. Dieser **Hausmeister** arbeitet als eigener Akteur mit der Kennung `local-assistant`. Seine Inhalte bleiben von den Originalinhalten des Benutzers unterscheidbar und nachvollziehbar.

Der Hausmeister darf innerhalb von ThreadDesk selbstständig arbeiten, zum Beispiel Threads und freigegebene Inhalte lesen, Zusammenfassungen erstellen, Informationen ordnen, Zusammenhänge erkennen sowie eigene Notizen und Whiteboard-Einträge anlegen oder weiterbearbeiten.

**Der Mensch hat Vorrang.** Selbstständige Hintergrundarbeit beginnt erst, wenn der Rechner wirklich ruht. Sobald wieder Benutzeraktivität erkannt wird oder die Rechnerlast steigt, startet der Hausmeister keine neue schwere Arbeit und macht dem Benutzer Platz. Pausierte Arbeit soll später sicher fortgesetzt werden können.

**Das lokale Modell wählt der Benutzer selbst.** ThreadDesk schreibt kein bestimmtes LLM vor. Welche Modelle sinnvoll funktionieren, hängt von Hardware, Arbeitsspeicher, Betriebssystem, gewünschter Geschwindigkeit und dem jeweiligen Modell ab. Genannte Modelle sind nur Startpunkte — keine Garantie für jede Hardware. Fehlende Modelle werden nicht automatisch heruntergeladen.

Ohne ausdrückliche Freigabe darf der Hausmeister keine Benutzeroriginale löschen oder überschreiben, keine Dateien außerhalb seines vorgesehenen ThreadDesk-Arbeitsbereichs verändern, keine externen Dienste oder kostenpflichtigen KI-Aufrufe starten und keine Geheimnisse oder Zugangsdaten verwenden.

**Grundprinzip:** selbstständig im eigenen lokalen Arbeitsbereich, zurückhaltend bei Rechnerressourcen und keine Eigenmächtigkeit außerhalb von ThreadDesk.

#### English

ThreadDesk can use a local AI assistant through Ollama. This **caretaker** runs as its own actor with the identifier `local-assistant`. Content it creates remains distinguishable from the user's original content and stays traceable.

Within ThreadDesk, the caretaker may work independently: it can read threads and permitted content, create summaries, organize information, detect relationships, and create or refine its own notes and whiteboard entries.

**The human always has priority.** Autonomous background work starts only when the computer is genuinely idle. As soon as user activity returns or system load rises, the caretaker does not start new heavy work and yields resources to the user. Paused work should be able to resume safely later.

**The user chooses the local model.** ThreadDesk does not prescribe a specific LLM. Which models work well depends on the computer, available memory, operating system, desired speed, and the model itself. Any named models are starting points only — not a guarantee for every hardware configuration. Missing models are not downloaded automatically.

Without explicit permission, the caretaker may not delete or overwrite the user's original content, modify files outside its designated ThreadDesk workspace, use external services or paid AI calls, or access secrets or credentials.

**Core principle:** independent inside its own local workspace, restrained with computer resources, and no unilateral action outside ThreadDesk.

[Produktseite](https://threaddesk.netzwerkpunkt.de/)

---

## Für Entwickler

ThreadDesk ist eine lokale Control-Layer vor Gnom-Hub-V1. Die Grenze ist Teil des Produkts: Übergaben werden vorbereitet, aber nicht automatisch extern gesendet oder ausgeführt. Der optionale lokale Hausmeister ist davon getrennt und darf nur innerhalb der dokumentierten lokalen Grenzen arbeiten.

### Wichtige Befehle

| Aufgabe | Befehl |
|---|---|
| Threads anzeigen | td list |
| Thread wechseln | td switch 1 |
| Status setzen | td status active |
| Snapshot speichern | td snap save "vor-umbau" |
| Prompt vorbereiten | td prompt |
| Handoff schreiben | td handoff |
| Lokale Oberfläche | td serve |
| MCP-Server | td mcp |
| Wissen für Menschen/KIs exportieren | td graph --export --format markdown |
| Vollständige JSON-Rundreise | td graph --export --format json |
| Tabelle für Calc/Excel | td graph --export --format csv --output wissen.csv |
| Arbeitsmappe mit getrennten Blättern | td graph --export --format xlsx --output wissen.xlsx |
| Wissenskarte als SVG | td graph --export --format svg --output karte.svg |
| Wissenskarte als PDF | td graph --export --format pdf --output karte.pdf |
| Exportpaket prüfen | td graph --export --format package --preview |
| Exportpaket schreiben | td graph --export --format package --output wissen.zip |
| Ausführung sperren | td gate freeze |
| Sprache umschalten | td --lang en list |

CSV und XLSX verwenden dieselbe geprüfte Auswahl wie JSON und Markdown. Private
Knoten bleiben ohne `--include-private` draußen. CSV schreibt Knoten,
Beziehungen und Quellen als normalisierte Tabelle. XLSX braucht `--output` und
legt dafür die drei übersichtlichen Blätter **Wissen**, **Beziehungen** und
**Quellen** an. Inhalte, die mit Excel-Formelzeichen beginnen, werden als Text
gespeichert.

SVG und PDF zeigen eine statische Wissenskarte mit lesbaren Bezeichnungen,
stabilen IDs, Beziehungen, Legende, Erstellzeit und aktiven Typ-/Statusfiltern.
Auch hier bleiben private Knoten standardmäßig ausgeschlossen.

### Sprache

ThreadDesk spricht Deutsch und Englisch — Oberfläche und Kommandozeile.

| Weg | Beispiel |
|---|---|
| Einmalig | `td --lang en list` |
| Dauerhaft | `export THREADDESK_LANG=en` |
| Automatisch | aus `LC_ALL`, `LC_MESSAGES` oder `LANG` |
| Oberfläche | Schalter oben rechts, merkt sich die Wahl ein Jahr |

Ohne Angabe ist Deutsch die Voreinstellung. Die Gliederungswörter der
Kommandozeilenhilfe (`usage:`, `options:`) kommen aus Python selbst und
bleiben englisch.

### Sprachebene: Klartext oder Fachsprache

Unabhängig von Deutsch/Englisch gibt es zwei Sprachebenen. **Klartext ist der
Normalfall, Fachsprache ist zuschaltbar** — nie umgekehrt. Wer die Begriffe
kennt, schaltet sie ein; wer sie nicht kennt, wird nicht mit ihnen überfahren.

| Weg | Beispiel |
|---|---|
| Einmalig | `td --mode expert gate` |
| Dauerhaft | `export THREADDESK_MODE=expert` |
| Oberfläche | Schalter oben rechts neben DE/EN, merkt sich die Wahl ein Jahr |

| Klartext (Standard) | Fachsprache |
|---|---|
| Schranke · Übergabe · Zwischenstände | Gate · Paket · Snapshots |
| `geschlossen: nein` · `heute losgeschickt` · `wartezeit: 15s` | `frozen: nein` · `execute heute` · `cooldown: 15s` |

Die Sprachebene wird **nicht** aus dem Browser oder der Umgebung geraten:
Klartext gilt für alle, bis jemand etwas anderes sagt.

Für die manuelle Entwicklerinstallation: `python3 -m pip install -e ".[dev,ui]"`. Daten liegen unter `~/.threaddesk/`.

### Gemeinsame Bedienbasis / Shared interface

Die vorhandene NetzwerkPunkt-Bedienbasis 0.1 aus dem Designstand wird selektiv
übernommen: `networkpunkt.css` (Blob `673f4e265c8c46618ba86d9e98f8da09fd0bf107`),
kleiner ThreadDesk-Adapter, Systemschrift und lokale Assets. Die aktuelle
Entscheidung ersetzt die alten R2-Zahlen; historische Belege bleiben datiert in
[GOLDENRULES §18/19](../docs/usability/GOLDENRULES.MD) und [COVERAGE](../docs/usability/COVERAGE.md).

| Rolle | Aktueller Wert |
| --- | --- |
| Metadaten / Lesetext / Abschnitt / Titel | 12 / 14 / 16 / 24 px |
| Einzeilige Felder und Aktionen | 40 px |
| Abstände | 4 / 8 / 12 / 16 / 24 / 32 px |
| Grundfläche / Arbeitsfläche / Hover | `#121316` / `#1a1c20` / `#25282e` |
| Text / Nebentext / Eingaberahmen | `#edf0f4` / `#afb6c1` / `#808996` |

Der Arbeitsinhalt dominiert; Threadpflege, Verlauf und Zusatzwerkzeuge sind
benannt aufklappbar. Der Desktop bleibt ab 1180×760 CSS-Pixeln dreigeteilt;
kleinere Ausschnitte und Zoom sind scrollbar, kein automatischer Mobilumbau.
Verborgene Laufleisten erhalten Tastaturzugriff und sichtbaren Fokus. Zustände
haben Klartext, nicht nur Farbe; keine pauschale Barrierefreiheitszertifizierung.

Deutsch und Englisch bleiben im vorhandenen Katalog; Klartext ist Standard,
Fachsprache optional. Rückgabe, ausdrückliche Ergebnisentscheidung und
Gesamtauftragsabnahme bleiben getrennt. Ungespeicherter Text oder eine fehlende
Speicherbestätigung werden sichtbar; Verbindungsfehler versenden nichts erneut.

The source reuses the existing shared design rather than introducing another UI.
The desktop composition, progressive disclosure, keyboard access and DE/EN copy
are checked in isolated real-browser flows. These source changes do not update an
installed desktop download. Result delivery, explicit review and overall project
acceptance remain separate; an uncertain write response is never retried automatically.

### Wie dieses Projekt entsteht

**System Designer & Product Architect: Daniel Filipek (landjunge)**

Produktvision, gewünschtes Verhalten und Grenzen kommen von mir. KI unterstützt Implementierung, Tests und Dokumentation. Code und Verhalten müssen überprüfbar bleiben.

### Dokumentation

- [Benutzeroberfläche](../docs/UI.md)
- [MCP](../docs/MCP.md)
- [Grok-Handoff](../docs/GROK.md)
- [TollGate-Grenze](../docs/TOLLGATE.md)
- [Gnom-Hub-V1-Handoff](../docs/GNOM.md)

---

**ThreadDesk beantwortet eine Frage: Was ist der Stand?**
Teil von [NetzwerkPunkt](https://netzwerkpunkt.de/) – eigenständig, local-first und ohne versteckte Ausführung.


### Gesprächsverwaltung / Conversation administration (M1 source)

Der aktuelle Quellstand ergänzt `thread_manage` für Anlegen, Bearbeiten,
Notizen/Dateiverweise, Projekt-/Eltern-/Threadzuordnung, Archivieren,
Wiederherstellen und explizites Löschen archivierter Threads. Exakte IDs,
erwartete Revision und persistente Operationskennung verhindern stille
veraltete Änderungen und doppelte Wiederholungen. Threadverwaltung startet
keine Agenten. [Vertrag und vollständige MCP-Fähigkeitstabelle](../docs/MCP.md).

The current source provides revision-bound local administration through
`thread_manage`, while preserving the existing MCP tools. Organizational links
are metadata, not filesystem moves. Context management never starts agents.
This source capability is separate from the published desktop 0.1.1rc1 download,
the full historical design PR #66, and an actually configured KiraBridge peer.
Internet team operation remains a separate server/identity deployment decision.

### Zugeordnete Übergabe / Bound handoff (M2 source)

`issue_handoff` stellt einen konkreten Threadstand idempotent aus; gespeicherter
Snapshot, Threadrevision und Inhaltshash bleiben von Handoff-/Bridge-/Laufkennungen
getrennt. Neue Bridge-Rückgaben verwenden die strikte ausgestellte Laufbindung:
auch die erste veraltete Rückgabe wird abgewiesen. Rückfragen/Antworten bleiben
am Lauf und im bestehenden Whiteboard zugeordnet; „Antwort gespeichert“ behauptet
keine bereits fortgesetzte KI. Lieferungen bleiben ungeprüft bis Nutzerentscheidung.

Issued handoffs and accepted run references are durable; reconnect reads them
instead of creating another job. Source file hashing is bounded and enabled only
for fixed operator roots; missing/unverifiable file evidence remains unknown.
No raw secrets, automatic execution, general Git attestation or new Internet
server are added. [Exact tools, limits and state semantics](../docs/MCP.md).


### Wissen und Wiedereinstieg / Knowledge and re-entry (TD-C03 source)

`knowledge_manage` speichert referenzierte Entscheidungen, offene Fragen,
verworfene Vorschläge und Aufgaben über denselben MCP-Zugang. Erwartete Thread-
und Knotenrevision, persistente Operationskennung und die bestehende Quittung
schützen vor stiller Überschreibung und Doppelung. Eine Korrektur erhält den alten
Beschluss als superseded und verknüpft den neuen. `get_reentry` findet gespeicherten
Wiedereinstieg, letzte Entscheidungen, Fragen/Aufgaben und Quellen nach Neustart.
Unbekannte Herkunft bleibt unknown; confirmed ist eine fachliche Entscheidung,
kein Funktions- oder Berechtigungsnachweis.

Neue ausgestellte Handoffs enthalten nur einen begrenzten lokalen Wissenskontext
(32 Items / 32 KiB, mit Anzahl und Trunkierung), getrennt nach Status und Herkunft.
Alte issued-Pakete und Hashes werden nicht nachträglich erweitert. `get_return`
liest genau eine bereits zugeordnete Rückgabe, ohne fremde Inbox-Inhalte über MCP
zu übertragen. Die Nutzerentscheidung bleibt ein eigener `review_return`-Schritt.

The existing graph and Thread.extra store knowledge; no second queue or database.
Source references remain unverified and do not grant execution rights. Every
knowledge mutation raises the Thread revision. New handoffs bind local graph
content; old stored handoffs keep their exact payload and receipt. Reconnecting
reads receipts/state instead of replaying an uncertain write. See the actual
[MCP capability catalog and examples](../docs/MCP.md), [TD-C03 evidence](../docs/evidence/seven-tools-20261018/TD-C03.md)
and [dated interface coverage](../docs/usability/COVERAGE.md).

Existing setup: install the source as described above, run `td mcp` (or
`python3 -m threaddesk.ui.mcp_stdio`) with explicit `THREADDESK_HOME` and optional
`THREADDESK_STORAGE=json|sqlite`. KiraBridge uses a fixed operator-configured peer;
requests cannot choose an executable, store or wider rights. Older desktop writers
are not a schema-6 SQLite compatibility guarantee. Keep a backup and the correct
writer/source pin; these changes do not migrate the real user workspace for a test.
