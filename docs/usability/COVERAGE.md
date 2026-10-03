# Abdeckungsmatrix ThreadDesk

Technischer Nachweis zum aktuellen Funktionsumfang. Verbindliche Entscheidungen
stehen nur in `GOLDENRULES.MD`. Diese Datei hält Ablaufkennungen, Prüfstatus und
Belege fest. Sie ist keine zweite Regelquelle.

Stand der Matrix: 2026-10-03. Designergänzung: siehe TD-DESIGN-01 unten.
Vorherige Codebasis: Branch `accept/browser-coverage`
(Backup-Reparatur `54f2ac0` plus Dokumentationsstand `70b0051`). Die frühere
Linux-Runde am Reparaturcommit bleibt ein Beleg für genau diesen Commit:
560 bestanden, 0 übersprungen, zweimal, darunter 34 Chromium-Fälle. Sie ist kein
Nachweis für diesen Mac, für Safari, für Firefox oder für eine Nutzerinstallation.

Legende: **nachgewiesen** heißt, der genannte Lauf hat das Nutzerergebnis geprüft.
**offen** heißt, die Oberfläche oder der Vertrag ist im Code, der Nutzerablauf
auf diesem Stand aber noch nicht belegt. **geplant** heißt, beschlossen und
ausdrücklich nicht Teil der jetzigen Browser-Abnahme. **außerhalb** heißt, nicht
beauftragt.

Hilfe, Video und Audio sind bei jedem Ablauf noch leer. Sie entstehen erst aus
bestandenen Läufen und werden hier nachgetragen. Aktive Voice-Hilfe und native
Apps sind nach Abschnitt 16 zuletzt dran.

## TD-START-01 Leerer Start

- Nutzerziel: Orientierung ohne Konto und ohne vorhandene Threads.
- Voraussetzungen: neuer synthetischer Arbeitsbereich, kein `~/.threaddesk`.
- Rolle: lokale Einzelperson. Datenbereich: nur dieser Arbeitsbereich.
- Schritte: Anwendung öffnen, Sprache Deutsch wählen, leere Fläche lesen.
- Erwartet: Hinweis zum Auswählen und der leere Listenzustand, kein Anmeldedialog.
- Fehlerfälle: noch nicht geprüft sind Abbruch vor dem ersten Thread und englische Leermeldung.
- Test: `tests/test_desk_browser.py::test_user_keeps_notes_and_snapshot_across_restart`
- Status: nachgewiesen am 2026-10-03 auf diesem Mac. Echtes Chrome-Fenster vorn, Playwright 1.63.0, Python 3.12.13, synthetischer Arbeitsbereich, 26,42 Sekunden, ein bestandener Lauf. Kein Safari, kein Firefox, keine Nutzerinstallation.
- Fehler: keiner in diesem Ablauf. Belege liegen außerhalb des Repos, weil sie nur synthetische Oberfläche zeigen und nicht mitversioniert werden: `Desktop/ThreadDesk-Abnahme/`.

## TD-THREAD-01 Thread anlegen

- Nutzerziel: einen benannten Thread mit Beschreibung anlegen.
- Voraussetzungen: TD-START-01.
- Rolle: lokale Einzelperson. Datenbereich: ein Thread.
- Schritte: Neu öffnen, leeres Absenden, dann Titel mit Umlauten und Beschreibung anlegen.
- Erwartet: leeres Absenden legt nichts an. Danach steht der Titel in der Liste und die Beschreibung im Schreibtisch.
- Fehlerfälle in diesem Lauf: leerer Titel. Offen: Doppelklick, zu langer Titel, Archiv, Umbenennen, Wechsel zweier Threads.
- Test: derselbe Browserfall.
- Status: Anlegen mit Umlaut und leerem Absenden nachgewiesen, gleicher Lauf wie TD-START-01.
- Fehler: keiner bekannt.

## TD-THREAD-02 bis TD-THREAD-05 Wechsel, Beschreibung, Umbenennen, Archiv

- Nutzerziel: zwischen Threads wechseln, Beschreibung ändern, umbenennen, archivieren und wiederfinden.
- Voraussetzungen: mindestens zwei Threads.
- Rolle: lokale Einzelperson.
- Status: Wechsel und Umbenennen nachgewiesen in `test_user_renames_switches_archives_and_keeps_file_paths`, Chrome vorn, 20,17 Sekunden, 2026-10-03. Beschreibung ändern und die Statuschips idea, active, paused, done sind nachgewiesen in `test_user_edits_description_status_and_whiteboard_order`, Chrome vorn, 14,56 Sekunden, 2026-10-03. Die Beschreibung „Neuer Zweck mit ÄÖÜ“ und der Status done bleiben nach Neuladen und nach dem Wechsel zu einem zweiten Thread. Ein zweiter Klick auf done lässt den Status stehen, ohne Fehlermeldung. Archivieren nimmt den Thread aus der Liste. Der Datensatz bleibt im Arbeitsbereich. Eine Schaltfläche, ihn wieder in die Liste zu holen, gibt es nicht. Dafür gibt es nur `td unarchive` auf der Kommandozeile. Die englischen Sätze dazu stehen in `test_user_reads_rename_and_archive_in_english`, Chrome vorn, 26,91 Sekunden, 2026-10-03: „Renamed: First renamed“, „Archive thread? It disappears from the list.“, „Archived: Second thread“ und „Pick a thread on the left“. Die deutschen Sätze dazu fehlen. Der archivierte Titel bleibt gespeichert.

## TD-NOTE-01 Notiz bleibt

- Nutzerziel: eine Notiz speichern und sie nach Neuladen und neuem Start wiederfinden.
- Voraussetzungen: ein angelegter Thread.
- Rolle: lokale Einzelperson. Datenbereich: `ThreadContext.notes` dieses Threads.
- Schritte: Notiz eintragen, Notiz speichern, Seite neu laden, Prozess beenden, neu starten, dieselbe Adresse öffnen.
- Erwartet: derselbe Text im Notizfeld. Die spätere Ersatznotiz ist nach dem Zwischenstand weg.
- Fehlerfälle in diesem Lauf: Neuladen und Prozessneustart. Offen: leere Notiz, sehr langer Text, Anhang-Kontrollkästchen, zwei Tabs.
- Test: derselbe Browserfall.
- Status: nachgewiesen, gleicher Lauf wie TD-START-01. Seite neu geladen und danach ein zweiter Serverprozess auf demselben Arbeitsbereich.
- Fehler: keiner bekannt.

## TD-SNAP-01 Zwischenstand ohne Verlaufsverlust

- Nutzerziel: Notizen auf einen benannten Stand zurücksetzen, ohne den Verlauf zu verlieren.
- Voraussetzungen: gespeicherte Notiz und ein angehängter Verlaufseintrag.
- Rolle: lokale Einzelperson. Datenbereich: Notizen plus Whiteboard dieses Threads.
- Schritte: Verlauf anhängen, Zwischenstand benennen, Notiz ändern und speichern, Laden bestätigen.
- Erwartet: Notiz ist wieder der erste Text. Der Verlaufseintrag und das Zwischenstand-Label bleiben. Die Bestätigung nennt den Notizverlust.
- Fehlerfälle in diesem Lauf: bestätigtes Laden. Offen: Abbrechen im Dialog, zweites Laden, beschädigte Snapshot-Datei.
- Test: derselbe Browserfall. Die Erwartung entspricht dem bestehenden Speichermodell: ein Zwischenstand kopiert den Kontext, nicht den Verlauf.
- Status: nachgewiesen, gleicher Lauf wie TD-START-01. Nach dem Neustart waren Notiz, Verlauf und Label noch da. Der ersetzte Notiztext war weg.
- Fehler: keiner bekannt. Daneben sichtbar, nicht Teil dieses Ablaufs: der Schreibtisch zeigt bei dieser Fenstergröße eine innere Laufleiste (TD-LAYOUT-01, offen). Die leere Hausmeister-Auswahl bleibt „keins“ (TD-HAUS-01).

## TD-FILE-01 Dateien

- Nutzerziel: eine Datei verknüpfen, den Verweis entfernen, eine fehlende Datei verstehen.
- Status: Pfad `Notizen/Überblick.txt` anlegen und wieder entfernen ist im selben Chrome-Lauf nachgewiesen. Die Oberfläche merkt sich nur den Pfad und öffnet die Datei nicht. Eine eigene Meldung „Datei fehlt“ ist deshalb nicht vorgesehen. Der native Dateidialog gehört zur späteren App-Runde.

## TD-BOARD-02 Herkunft, Konflikt, Wiederholung

- Nutzerziel: dieselbe externe Kennung nicht doppelt schreiben und einen abweichenden Text als Konflikt behalten.
- Status: Herkunft, Reihenfolge und Wiederholung über die Schaltfläche Anhängen sind im selben Chrome-Lauf nachgewiesen. Leeres Absenden hängt nichts an. Der erste Beitrag zeigt Prüferin und Entscheidung. Derselbe zweite Text bleibt zweimal stehen, mit zwei Kennungen, in derselben Reihenfolge nach Neuladen. Der aktuelle Stand zeigt die letzte Person, den letzten Text und den früheren nächsten Schritt. Ein abweichender Text zur selben externen Kennung hat im Schreibtisch keine Schaltfläche. Das bleibt in `tests/test_whiteboard.py` und `tests/test_whiteboard_merge.py`. TD-SNAP-01 deckt nur das einmalige Anhängen ab.

## TD-KNOW-01 Wissen

- Nutzerziel: Knoten und Beziehung anlegen, filtern, zwischen Liste und Karte wechseln.
- Status: Anlegen, leeres Absenden, Filter und der Weg zur Karte sind nachgewiesen in `test_user_creates_filters_and_opens_knowledge_on_the_map`, Chrome vorn, 13,20 Sekunden, 2026-10-03. Ein leerer Knoten wird nicht gespeichert. Der Filter auf den Typ task blendet „Projekt ÄÖÜ“ aus, Zurücksetzen holt ihn zurück. Eine Person und die Verbindung contains bleiben nach Neuladen. Die Karte zeigt beide Titel, die Linie und nach dem Klick den Zweck „Sichtbarer Zweck“. Die 19 Kartenfälle sind zusätzlich auf diesem Mac wiederholt, siehe TD-MAP-01.

## TD-MAP-01 Karte bedienen

- Nutzerziel: Auswahl, Zoom, Fokus, Detail, Tastatur, reduzierte Bewegung, mehrere Breiten.
- Status: 19 Fälle in `tests/test_ui_browser.py` auf diesem Mac, System-Chrome, 2026-10-03. Kopflos 9,58 Sekunden. Dieselben Fälle im vorderen Chrome, 75,53 Sekunden, 1,5 Sekunden je Aktion: Klick, Umschalt-Klick, Tastatur, Zoom um die Mitte, Einpassen, Ziehen bei 1280 und 600 Pixeln, Formen, Status ohne Farbe, Pfeil, reduzierte Bewegung und Ziehen eines Knotens. Der Linux-Stand von `54f2ac0` bleibt der ältere Beleg. Safari und Firefox sind offen.

## TD-HAND-01 Übergabe

- Nutzerziel: Prompt und Handoff vorbereiten und die Rückgabe als nicht ausgeführt erkennen, bis sie angenommen ist.
- Status: Oberfläche vorhanden (`partials/prompt.html`, `partials/packet.html`). Browsernachweis offen. Kein echter Gnom- oder Grok-Lauf in diesem Umfang.

## TD-HAUS-01 Hausmeister

- Nutzerziel: einschalten, ausschalten, ein vorhandenes lokales Modell wählen, Ausfall und Abbruch sehen.
- Status: Die leere Auswahl heißt „keins“ und bleibt gewählt, solange kein Modell gespeichert ist. „Modell übernehmen“ auf dieser leeren Auswahl löscht die Wahl und ruft dafür kein Modell auf. Nachweis im Chrome-Lauf und in `test_blank_model_clears_the_choice_without_calling_ollama`. Einschalten, Ausschalten, leerer Auftrag, fehlendes Modell und „Später erledigen“ sind auf diesem Mac im vorderen Chrome nachgewiesen, `test_user_switches_the_housekeeper_without_a_model`, 26,38 Sekunden, 2026-10-03. Leeres „Jetzt ausführen“ zeigt „Auftrag nicht ausgeführt“ und hängt nichts an. Ein ausgefüllter Auftrag ohne gespeichertes Modell zeigt „Kein lokales Modell gewählt“. „Später erledigen“ schreibt den Text in die lokale Warteschlange und meldet „Auftrag wartet“. Eine Abbruch-Schaltfläche gibt es in der Oberfläche nicht. Zusätzlich ein echter Auftrag an das bereits installierte `llama3.2:1b`, vorderes Chrome, 38,46 Sekunden, nur wenn `THREADDESK_HAUSMEISTER_LIVE=1`. Die normale Suite setzt die Variable nicht und ruft Ollama dafür nicht auf. Es wurde kein Modell heruntergeladen. Die Meldung ist „Auftrag angehängt“, der Verlauf enthält einen Eintrag des lokalen Hausmeisters. Der gespeicherte Text ist die Modellantwort. Das beweist keine brauchbare Zusammenfassung. Zusätzlich `test_user_reads_housekeeper_phases_in_english`, Chrome vorn, 32,98 Sekunden, 2026-10-03. Die Sätze lauten „Housekeeper“, „Ollama is reachable on this machine“, „none“, „No local model selected“, „Turn on“, „Turn off“, „Use model“, „What should be tidied?“, „Run now“, „Do later“, „Job was not run“, „Job is waiting“ und „Waiting for a job“. „Waiting for a job“ steht, nachdem ein bereits gelistetes Modell gespeichert und eingeschaltet ist, bevor ein Auftrag abgeschickt wird. Danach ist die Wahl wieder leer. „Waiting for a quiet moment“, „Working“ und „Paused. Someone is active.“ waren nicht sichtbar. Es wurde kein Modell gestartet und nichts angehängt. Die deutschen Sätze dazu fehlen. Ohne erreichbares Ollama oder ohne gelistetes Modell prüft derselbe Test nur den Satz, der wirklich steht, und verlangt die vier Auftragssätze nicht.

## TD-ROOM-01 Zwei Schreibtische

- Nutzerziel: Raum anlegen, beitreten, in zwei getrennten Prozessen synchronisieren.
- Status: Auf diesem Mac am 2026-10-03. `test_team_room_real_browser` mit JSON im vorderen Chrome, 126,15 Sekunden, 1,5 Sekunden je Aktion. SQLite derselbe Fall kopflos, 20,21 Sekunden. `test_two_live_servers_sync_a_room` in 7,72 Sekunden, die Ports 8765 und 8766 danach frei. Zwei getrennte Arbeitsbereiche, lokales HTTP auf 127.0.0.1. Die englischen Zustandsworte stehen zusätzlich in `test_user_reads_room_states_in_english`, 68,77 Sekunden. Privat, Nur-Lesen-Verhalten und SQLite bleiben der frühere Lauf. Firmen-Sync bleibt geplant (B2). Die Nutzerinstallation bleibt offen.

## TD-PRIV-01 und TD-ROLE-01

- Nutzerziel: private Einträge bleiben lokal. Nur-Lesen empfängt und veröffentlicht nicht. Offline, Neustart und Konflikt behalten beide Fassungen.
- Status: Derselbe JSON-Fensterlauf. Die private Notiz und der private Verlauf bleiben auf dem ersten Schreibtisch. Nur-Lesen empfängt den freigegebenen Eintrag, die Freigabe ist gesperrt, ein erzwungenes Mitschicken antwortet 403. Nach dem Stopp der Gegenstelle steht „Gegenstelle nicht erreichbar“, nach dem Neustart kommt der neue Eintrag an. Zwei abweichende Fassungen bleiben beide stehen. Wiederholtes Synchronisieren ändert die Anzahl nicht. Ein Raumrecht ist keine 4AllPass-Freigabe.

## TD-NOTION-01 Übernahme

- Nutzerziel: Bundle ansehen, Konflikt entscheiden, ausdrücklich importieren, Wiederherstellung verstehen.
- Status: neun Fälle in `tests/test_migration_browser.py` auf diesem Mac, System-Chrome, kopflos, 53,79 Sekunden, 2026-10-03. Vorschau, ausdrücklicher Import und Wiederherstellungs-Kopie zusätzlich im vorderen Chrome, 19,24 Sekunden, synthetisches Bundle. Notion bleibt das Arbeitsgedächtnis. Die Nutzerinstallation ist nicht beteiligt.

## TD-BACK-01 Sicherung

- Nutzerziel: Sicherung erhalten, in einem zweiten Arbeitsbereich öffnen, zum unveränderten Original zurückkehren.
- Status: vier Fälle in `tests/test_data_browser.py` auf diesem Mac, System-Chrome, kopflos, 21,21 Sekunden, 2026-10-03. JSON und SQLite, normaler Pfad und Verzeichnisverknüpfung. JSON ohne Verknüpfung zusätzlich im vorderen Chrome, 20,59 Sekunden. Die Datei kommt an, öffnet sich als eigener Arbeitsbereich, und der spätere Stand des Originals ist nach der Rückkehr wieder da. Die installierte App und der native Speicherdialog sind nicht belegt. Der native Dialog gehört an das Ende.

## TD-EXPORT-01 Export

- Nutzerziel: angebotene Exportformate erzeugen und öffnen können.
- Status: Auf diesem Mac am 2026-10-03, `test_user_opens_graph_json_and_exports_private_knowledge`, Chrome vorn, 19,59 Sekunden. „Graph-JSON“ zeigt den privaten Knoten „Export ÄÖÜ“ und das Schema `threaddesk.graph.v1`. Die Kommandozeile schreibt json, markdown und csv mit `--include-private`, jeweils mit dem Titel. svg, pdf, xlsx und package sind in diesem Lauf nicht geöffnet. Eine eigene Export-Seite ist nicht der aktuelle Hauptweg. Formate nicht erfinden.

## TD-I18N-01 Sprache und Ebene

- Nutzerziel: Deutsch und Englisch sowie Klartext und Fachsprache wechseln, ohne gemischte Oberfläche.
- Status: DE und EN wechseln Neu/New. Zusätzlich `test_user_switches_plain_and_expert_wording`, Chrome vorn, 25,64 Sekunden, 2026-10-03. „Zwischenstände“ wird zu „Snapshots“ und auf Englisch zu „Saved states“, jeweils zurück. Zusätzlich `test_user_reads_the_main_pages_in_both_languages`, Chrome vorn, 26,10 Sekunden, 2026-10-03. Leerer Schreibtisch, Tasten-Hilfe, Wissenspool, Karte und Sicherung zeigen die immer sichtbaren Sätze in beiden Sprachen. „Sprachebene“ und „Wording“ sind der Name der Navigation. Nach EN fehlen die geprüften deutschen Sätze auf der Sicherung; Karte, Wissenspool und Schreibtisch zeigen danach die englischen Sätze. Zusätzlich `test_user_reads_action_notices_in_english`, Chrome vorn, 30,63 Sekunden, 2026-10-03. Nach Anlegen, Beschreibung, Notiz, Verlauf und Pfad zeigt der Hinweis „Created“, „Description saved“, „Note saved“, „Entry appended“ und „File: src/notice.py“. Die deutschen Sätze dazu fehlen. Am offenen Thread stehen „Paths only. No upload, no opening.“ und „No file paths.“. Zusätzlich `test_user_reads_room_states_in_english`, JSON, zwei Prozesse, Chrome vorn, 68,77 Sekunden, 2026-10-03. Die Zustände lauten „Not connected“, „Connected“, „Synchronized“, „Changes waiting“, „Other side is not reachable“ und „Conflict kept“. Die Hinweise lauten „Room created“, „Invitation code“ und „Paired“. Die Rollen lauten „Owner“, „Member“ und „Read only“. Im Leseraum ist die Freigabe gesperrt, der Satz lautet „Read only – new entries stay private“. Die deutschen Sätze dazu fehlen. Der zweite Schreibtisch zeigt nach dem Konfliktabgleich nicht denselben Zustandsnamen. Beide Fassungen stehen auf beiden Schreibtischen. SQLite, die private Notiz und die 403-Antwort bleiben der frühere Lauf. Zusätzlich `test_user_reads_housekeeper_phases_in_english`, Chrome vorn, 32,98 Sekunden, 2026-10-03. „Waiting for a job“, „Job was not run“ und „Job is waiting“ sind sichtbar. „Waiting for a quiet moment“, „Working“ und „Paused. Someone is active.“ bleiben unbelegt. Zusätzlich `test_user_reads_rename_and_archive_in_english`, Chrome vorn, 26,91 Sekunden, 2026-10-03. „Renamed: First renamed“, „Archive thread? It disappears from the list.“, „Archived: Second thread“ und „Pick a thread on the left“ sind sichtbar. Die deutschen Sätze dazu fehlen. Fehlermeldungen außerhalb des Hausmeisters und die übrige Fachsprache sind nicht Satz für Satz geprüft. Ein englischer Migrationsfall liegt zusätzlich in `tests/test_migration_browser.py` vom Linux-Stand.

## TD-HELP-01 Hilfe und Rückweg

- Nutzerziel: Hilfe öffnen, lesen, schließen und von einem Fehler zurückkehren.
- Status: Tasten-Hilfe öffnet und schließt mit Escape. Im selben Lauf, 26,10 Sekunden, stehen die Tastensätze in der Hilfe auf Deutsch und auf Englisch. Ob jeder Satz zur Oberfläche eines offenen Threads passt, ist noch offen. Voice ist nicht Teil dieser Hilfe.

## TD-SEC-T01 bis T22

- Nutzerziel: die 22 Sicherheitsfälle aus GOLDENRULES Abschnitt 13.
- Status: geplant, nicht bestanden. Die lokale Testsuite beweist sie nicht. In dieser Runde keine Firmen- oder Kryptografiearchitektur bauen, nur um einen Status grün zu färben.

## TD-LAYOUT-01 Schreibtisch im Fenster

- Nutzerziel: den offenen Thread ohne Seitenlaufleiste bedienen.
- Historischer Status vor der Designüberarbeitung: gemessen. Bei 1440×900 scrollt die Seite nicht (`page`, `notes` und `side` ohne Überlauf im kurzen Thread). Eine innere Laufleiste erscheint, wenn Verlauf oder Seitenspalte höher sind als das Fenster. Das ist die vorhandene Spaltenscrollung, kein Seitenfehler. Offen bleibt, ob bei vollem Inhalt eine wichtige Schaltfläche nur durch Scrollen erreichbar ist.

- Erster Designstand 03.10.2026: Balken verborgen, Spaltenscrollung erhalten. Dieser Stand verwendete bei schmalen Fenstern noch einen Seitenfluss. Der anschließende Desktop-Beschluss ersetzt diesen Umbau; aktueller Nachweis unter TD-DESIGN-02.

## TD-VOICE-01 und TD-NATIVE-01

- Nutzerziel: gesprochene Hilfe sowie Installation auf Mac, Windows und Linux.
- Status: zurückgestellt bis die Browser-Abnahme steht. Der Desktop-Workflow startet native Builds bei einem Pull Request, der `src/`, `packaging/`, `scripts/`, `brand/` oder `pyproject.toml` ändert, und bei einem solchen Push auf `main`. Deshalb wird der Designstand als Feature-Branch ohne Code-PR gesichert; native Builds folgen erst dem späteren Bauauftrag.

## Gestrichen oder verschoben

- Vollsuite nur wegen eines neuen Planttexts wiederholen: verschoben. Der Linux-Nachweis am Reparaturcommit bleibt gültig, bis dieser Branch den Code darüber hinaus ändert. Gezielte Prüfung zuerst.
- Zweiter Orchestrator und Modellaufruf für jede triviale Auswahl: gestrichen. Der kleine Whiteboard-Hook bleibt die geplante Ergänzung aus Abschnitt 17, noch nicht implementiert.
- Native Builds jetzt: verschoben, Grund ist die Reihenfolge in Abschnitt 16 und der Workflow-Auslöser oben.
- Konkurrenzdatei zu GOLDENRULES: nicht angelegt.


## TD-DESIGN-01 Einheitliche Oberfläche

- Historischer Nachweis für Commit `a443dcd`, erster Durchgang. Die folgende
  Responsive-/Touch-Beschreibung ist durch TD-DESIGN-02 und GOLDENRULES §19
  abgelöst; die 172 bestandenen Tests gehören ausschließlich zu diesem Stand.
- Auftrag: alle vorhandenen Ansichten vereinheitlichen; scrollbar ohne sichtbare
  Scrollbalken. Verbindliche Regeln und Recherche: GOLDENRULES Abschnitt 18.
- Codebasis: `design/unified-interface`, aufgebaut auf dem gepushten Browserstand
  `828320d` (einschließlich neuer Import-/Backup-Nachweise). Keine Produktänderungen
  der anderen Arbeitslinie überschrieben.
- Umsetzung: eine Schriftfamilie und vier Rollen, gemeinsame 40-Pixel-Bedienhöhe
  (44 für Touch), feste Abstände, gleiche Breiten innerhalb zusammengehöriger
  Aktionsgruppen, gezielte Hauptaktion/Auswahl, vollständige Formularstile für
  Daten und Import, verständlich umbrechende schmale Ansichten, Dialogfokus.
- Designprüfung: `tests/test_design_browser.py`, 15 Fälle. Fünf echte Seiten bei
  1440×1000, 1280×800, 1024×768, 768×900, 375×812 und 320×800, jeweils DE und EN:
  60 Kombinationen. Hinzu kommen fünf Touch-Ansichten, Tastatur-Scrollen in
  Seitenleiste/Werkzeugen/Notizen/Verlauf, Dialogfokus, gespeicherte Bearbeitung und
  lesbare Fehlermeldung bei ungültiger Sicherung. Lange Inhalte sind synthetisch.
- Gemessen werden Seitenüberlauf, Bedienhöhe, abgeschnittene Buttonbeschriftungen
  und sichtbare Balken. Eine grüne DOM-Prüfung allein reicht nicht: Schreibtisch,
  Wissen, Karte, Daten, Import, leerer Start, Fehlerzustand und Hilfedialog wurden
  zusätzlich als Browserbilder angesehen und nachgebessert.
- Kontrastprüfung der gemeinsamen Text-/Statustokens gegen die drei Grundflächen:
  mindestens 5,8:1; Hauptaktion 9,47:1; Eingaberahmen über 3:1. Kein vollständiger
  WCAG-Audit. Native Dateiauswahldialoge und Browsermeldungen folgen weiterhin dem
  Betriebssystem bzw. Browser.
- Gefundene und behobene Darstellungsfehler: gebrochene Statusmarken, zu hohe
  Kopfbelegung, Navigation bei schmaler Restbreite, uneinheitliche Datei-Eingaben
  und eine zu schwache graue Statusfarbe. Ein alter Test erwartete noch den
  verworfenen grauen Akzent und wurde an den dokumentierten Beschluss angepasst.
- Abschluss: **172 Tests bestanden, 0 fehlgeschlagen, 0 übersprungen**, 135,05 Sekunden am 03.10.2026. Darunter die 15 neuen Designfälle sowie bestehende Schreibtisch-, Karten-, Raum-, Sicherungs-, Import-, Sprach- und Assetprüfungen. JavaScript-Syntax und Git-Diff-Prüfung bestanden.
- Umgebung: Linux, Python 3.12, Playwright 1.58.0, Chromium 145.0.7632.6, kopflos,
  echte lokale Server und ausschließlich synthetische Arbeitsbereiche.
- Grenzen: keine Mac-/Safari-/Firefox-/Windows-/Linux-App-Abnahme, keine automatische
  Auslieferung auf das Nutzergerät, keine neuen Firmen-Sicherheitsnachweise. Voice,
  Videos und native Builds bleiben in der vereinbarten Reihenfolge.
- [Gespeicherte Designvorschau des Schreibtischs](design-2026-10-03/desk.png).
  Das Bild zeigt synthetische Inhalte, keine echte Nutzerinstallation.

Reproduzierbarer Aufruf (installierte UI-/Dev-/Browser-Abhängigkeiten vorausgesetzt):

```sh
python -m pytest tests/test_design_browser.py tests/test_data_browser.py tests/test_migration_browser.py tests/test_ui_assets.py tests/test_ui_desk_layout.py tests/test_i18n.py tests/test_desk_browser.py tests/test_ui_browser.py tests/test_room_browser.py -q
```

Für einen bereits installierten Chromium kann `THREADDESK_CHROMIUM` auf dessen
Binary zeigen. Der Designnachweis darf nicht als übersprungener Test grün werden,
wenn kein Browser vorhanden ist. Es wurde kein nativer Build ausgelöst; der
Code wird als Branch ohne den native Builds auslösenden Code-PR gesichert.

## TD-DESIGN-02 Gemeinsame Bedienbasis, fester Desktop

- Abschluss am 03.10.2026: **174 Tests bestanden, 0 fehlgeschlagen,
  0 übersprungen**, 133,64 Sekunden. JavaScript-Syntaxprüfung beider geänderter
  Skripte und Git-Diff-Prüfung bestanden. Die vorherigen fehlgeschlagenen
  Durchgänge waren Reparaturrunden und zählen nicht als Abnahme.
- Auftrag: alle fünf Produkte sollen derselben Gestaltungsfamilie folgen;
  Hierarchie beruhigen und die neue Desktop-Entscheidung von Daniel umsetzen.
  Verbindliche Begründungen und Übernahmeplan: GOLDENRULES Abschnitt 19.
- Gemeinsamer Kern: `networkpunkt.css` und optionales `networkpunkt.js` ohne
  externe Laufzeitabhängigkeiten. ThreadDesk lädt den Kern und verwendet dessen
  Tokens. Die interaktive `design-reference.html` zeigt alle fünf Produkte mit
  denselben Komponenten und kennzeichnet ihre Inhalte als synthetische Probe.
  Die anderen vier Produkt-Repositories sind noch nicht umgestellt.
- Figma: [Familientafel und Grundlagen](https://www.figma.com/design/B9Cj8P12JwXo7BGmW3Icu0?node-id=2-59),
  51 Variablen (27 semantische Aliase), vier Textstile. Roboto ist der vorhandene
  Fallback für die Figma-Darstellung. Kein fertiges Figma-Komponentenpaket.
- ThreadDesk: Arbeitsaufgabe vor Verlauf, eine dominante Hauptaktion,
  Threadpflege und Zusatzwerkzeuge in benannten aufklappbaren Bereichen.
  Öffnungszustände überstehen Neuladen und HTMX-Aktualisierung; Tastaturkürzel
  öffnen ihre Zielbereiche. Fehler und der Schrankenstatus bleiben sichtbar.
- Desktop statt automatischem Mobilumbau: feste Spalten, mindestens 1180×760
  CSS-Pixel, Referenz 1440×900. Größere Fenster geben der Mitte mehr Raum;
  kleinere Ausschnitte scrollen bei gleicher Anordnung. Bedienhöhe 40 Pixel,
  auch bei einem groben Zeiger. Keine Smartphone- oder WCAG-Reflow-Abnahme.
- 17 Designfälle: fünf echte Seiten bei 1920×1080, 1440×900, 1280×800 und
  1180×760, jeweils DE/EN (40 Kombinationen); fünf zusätzliche Ansichten mit
  grobem Zeiger; alle fünf Familienproben bei drei Breiten (15 Kombinationen).
  Dazu geöffnete Zusatzbereiche bei zwei Breiten, gespeicherte Bearbeitung,
  ungültige Sicherung, Tastatur-Scrollen, Hilfedialog, Zustandserhalt und
  Snapshot-Kürzel. Bei 1024×700 bleiben die Spalten bestehen und die letzte
  Übergabeaktion gelangt durch Tastaturfokus vollständig in den Ausschnitt.
- Gemessen: Bedienhöhe, Seitenbreite im vorgesehenen Arbeitsbereich,
  abgeschnittene Beschriftungen, sichtbare Balken und Skriptfehler. Verdeckte
  Inhalte geschlossener Bereiche zählen nicht als sichtbare Elemente; ihre
  geöffneten Zustände werden separat geprüft. Die bestehenden Funktionsfälle
  öffnen die neuen Bereiche durch echte Klicks. Sicherungsprüfungen lesen nach
  Öffnen der Notizen den tatsächlichen gespeicherten Feldwert.
- Sichtprüfung: echte ThreadDesk-Oberfläche mit synthetischen Inhalten bei
  Referenz- und Mindestgröße sowie die Familientafel. Behoben wurde ein echter
  Engpass: Geöffnete Kopffelder mit langem Titel verdrängten die Notizen. Der
  Kopf kann jetzt selbst scrollen; Notizen und Werkzeuge bleiben erreichbar.
- Kontrast der Text-/Statustokens gegen die drei Grundflächen: mindestens
  7,04:1; Eingaberahmen mindestens 4,18:1. Kein vollständiger WCAG-Audit.
- Umgebung: Linux, Python 3.12, Playwright 1.58.0, Chromium 145.0.7632.6,
  kopflos, echte lokale Server, ausschließlich synthetische Arbeitsbereiche.
- Grenzen: keine Auslieferung auf Daniels Installation, keine Abnahme aller
  fünf Produkte, kein Mac-/Safari-/Firefox-Nachweis und keine native Ausgabe.
  Die sichtbare Nutzerabnahme des Designs bleibt eigenständig. Groks
  Hilfe-/Videoauftrag, aktive Voice und native Apps behalten ihre Reihenfolge.
- Gespeicherte Bilder: [Desktop](design-2026-10-03/desktop.png),
  [gemeinsame Familienprobe](design-2026-10-03/family.png).

Der oben dokumentierte pytest-Aufruf ist weiterhin der reproduzierbare
Browser-/Asset-/Sprach-Prüfumfang; er ist keine vollständige Projekttestsuite.

## TD-DESIGN-03 Gemeinsame Desktopbasis und Prüfbranch zusammengeführt

Stand 03.10.2026: `design/unified-interface` mit dem in Notion gemeldeten
`accept/browser-coverage` bis `4cb1bd2a3c5c3ea78425a6008693cb8f2faeac88`
zusammengeführt. Der Hausmeister meldet leere Aufträge sichtbar; HTMX bekommt
den Fehlerinhalt zum Einsetzen. Neuere Mac-Prüfberichte bleiben oben als
Nachweis ihrer jeweiligen Umgebung erhalten.

Lokale Integrationsprüfung: **65 bestanden, 1 übersprungen, 84,79 Sekunden**.
`tests/test_desk_browser.py`, `tests/test_hausmeister.py`,
`tests/test_ui_browser.py`, `tests/test_room_browser.py`; Chromium 145 unter
Linux, getrennte synthetische Arbeitsbereiche. Enthält englische Hausmeister-,
Raum-, Umbenennungs-/Archivhinweise. Die Tests öffnen Zusatzbereiche durch
echte Klicks. Die neue Thread-Schaltfläche wird genau einmal geklickt und
auf das Formular gewartet; ein sofortiger zweiter Klick hatte es wieder geschlossen.
Der echte Modellauftrag ist ohne `THREADDESK_HAUSMEISTER_LIVE=1` ausdrücklich
übersprungen und zählt nicht als bestandener Modelltest. Kein neuer nativer Bau.

Die 174 Prüfungen von TD-DESIGN-02 gelten weiter für den dort benannten
vorherigen Commit; diese Runde behauptet keinen erneuten Gesamtlauf.

Die vier weiteren Produktadapter liegen in ihren eigenen Repositories mit
bytegleicher CSS-Basis aus `b0b6815`, eigenen Prüfbildern und `checks.json`:
4AllPass (43 Frontend-Tests, 3 Chromium-Abläufe), TollGate (97 gezielte Tests
und Budgetablauf), Gnom-Hub-V1 (1038 bestanden, 3 übersprungen, kompletter
Qualitätslauf sowie lokale Oberflächenwege), NetzwerkPunkt (Anker, Produktziele,
Desktop-Scrollen). Dies ist eine implementierte gemeinsame Grundlage;
vollständige produktübergreifende Nutzerabnahme, Hilfevideos und Voice bleiben offen.
