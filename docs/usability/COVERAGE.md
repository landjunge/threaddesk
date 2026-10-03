# Abdeckungsmatrix ThreadDesk

Technischer Nachweis zum aktuellen Funktionsumfang. Verbindliche Entscheidungen
stehen nur in `GOLDENRULES.MD`. Diese Datei hält Ablaufkennungen, Prüfstatus und
Belege fest. Sie ist keine zweite Regelquelle.

Stand der Matrix: 2026-10-03. Codebasis: Branch `accept/browser-coverage`
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
- Status: Wechsel und Umbenennen nachgewiesen in `test_user_renames_switches_archives_and_keeps_file_paths`, Chrome vorn, 20,17 Sekunden, 2026-10-03. Beschreibung ändern und die Statuschips idea/active/paused/done bleiben offen. Archivieren nimmt den Thread aus der Liste. Der Datensatz bleibt im Arbeitsbereich. Eine Schaltfläche, ihn wieder in die Liste zu holen, gibt es nicht. Dafür gibt es nur `td unarchive` auf der Kommandozeile.

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
- Fehler: keiner bekannt. Daneben sichtbar, nicht Teil dieses Ablaufs: der Schreibtisch zeigt bei dieser Fenstergröße eine innere Laufleiste (TD-LAYOUT-01, offen). Der Hausmeister zeigt ein Modell in der Liste, während der Satz sagt, dass keines gewählt ist (TD-HAUS-01, offen).

## TD-FILE-01 Dateien

- Nutzerziel: eine Datei verknüpfen, den Verweis entfernen, eine fehlende Datei verstehen.
- Status: Pfad `Notizen/Überblick.txt` anlegen und wieder entfernen ist im selben Chrome-Lauf nachgewiesen. Die Oberfläche merkt sich nur den Pfad und öffnet die Datei nicht. Eine eigene Meldung „Datei fehlt“ ist deshalb nicht vorgesehen. Der native Dateidialog gehört zur späteren App-Runde.

## TD-BOARD-02 Herkunft, Konflikt, Wiederholung

- Nutzerziel: dieselbe externe Kennung nicht doppelt schreiben und einen abweichenden Text als Konflikt behalten.
- Status: Vertragstests vorhanden (`tests/test_whiteboard.py`, `tests/test_whiteboard_merge.py`). Sichtbarer Browsernachweis für Konflikt und Wiederholung offen. TD-SNAP-01 deckt nur das einmalige Anhängen ab.

## TD-KNOW-01 Wissen

- Nutzerziel: Knoten und Beziehung anlegen, filtern, zwischen Liste und Karte wechseln.
- Status: Oberfläche und API vorhanden. Die 19 Kartenfälle in `tests/test_ui_browser.py` sind am Linux-Chromium von `54f2ac0` gelaufen. Anlegen, Filtern und der Weg Liste-Karte sind damit nicht belegt. Auf diesem Mac nicht wiederholt.

## TD-MAP-01 Karte bedienen

- Nutzerziel: Auswahl, Zoom, Fokus, Detail, Tastatur, reduzierte Bewegung, mehrere Breiten.
- Status: 19 Fälle in `tests/test_ui_browser.py`, Linux-Chromium `54f2ac0`. Dieser Mac, Safari und Firefox offen. Nicht erneut laufen lassen, nur weil die Matrix neu ist.

## TD-HAND-01 Übergabe

- Nutzerziel: Prompt und Handoff vorbereiten und die Rückgabe als nicht ausgeführt erkennen, bis sie angenommen ist.
- Status: Oberfläche vorhanden (`partials/prompt.html`, `partials/packet.html`). Browsernachweis offen. Kein echter Gnom- oder Grok-Lauf in diesem Umfang.

## TD-HAUS-01 Hausmeister

- Nutzerziel: einschalten, ausschalten, ein vorhandenes lokales Modell wählen, Ausfall und Abbruch sehen.
- Status: Die leere Auswahl heißt jetzt „keins“ und ist gewählt, solange kein Modell gespeichert ist. „Modell übernehmen“ auf dieser leeren Auswahl löscht die Wahl und ruft dafür kein Modell auf. Das ist im Chrome-Lauf und in `test_blank_model_clears_the_choice_without_calling_ollama` nachgewiesen. Einschalten, Ausschalten und ein echter Auftrag an Ollama sind offen. Ein Lauf beweist keine Antwortqualität.

## TD-ROOM-01 Zwei Schreibtische

- Nutzerziel: Raum anlegen, beitreten, in zwei getrennten Prozessen synchronisieren.
- Status: `tests/test_room_browser.py` und `tests/test_room_sync_e2e.py` am Linux-Stand `54f2ac0`. Das ist lokales HTTP, kein Internet-Sync. Dieser Mac nicht wiederholt. Firmen-Sync bleibt geplant (B2).

## TD-PRIV-01 und TD-ROLE-01

- Nutzerziel: private Einträge bleiben lokal. Nur-Lesen empfängt und veröffentlicht nicht. Offline, Neustart und Konflikt behalten beide Fassungen.
- Status: Vertrags- und Zwei-Prozess-Tests am Linux-Stand. Sichtbare Wiederholung auf diesem Mac offen. Ein Raumrecht ist keine 4AllPass-Freigabe.

## TD-NOTION-01 Übernahme

- Nutzerziel: Bundle ansehen, Konflikt entscheiden, ausdrücklich importieren, Wiederherstellung verstehen.
- Status: sieben benannte Fälle in `tests/test_migration_browser.py`, in der Linux-Runde als Teil der 9 Migrationsfälle gezählt. Dieser Mac nicht wiederholt. Keine Umschaltung von Notion auf ThreadDesk als einziges Gedächtnis.

## TD-BACK-01 Sicherung

- Nutzerziel: Sicherung erhalten, in einem zweiten Arbeitsbereich öffnen, zum unveränderten Original zurückkehren.
- Status: vier Chromium-Fälle in `tests/test_data_browser.py` (JSON und SQLite, normaler Pfad und Verzeichnisverknüpfung) am Commit `54f2ac0`, Linux. Die zwei Codekorrekturen sind damit dort belegt. Die konkrete macOS-Nutzerinstallation und der native Speicherdialog sind nicht belegt. Nativer Dialog gehört an das Ende, nach der Browser-Abnahme. Diesen Fall hier nicht noch einmal als erste Lücke bauen.

## TD-EXPORT-01 Export

- Nutzerziel: angebotene Exportformate erzeugen und öffnen können.
- Status: Wissens-Export existiert im Dienst und in der Kommandozeile. Eine eigene Export-Seite im Schreibtisch ist nicht der aktuelle Hauptweg. Browsernachweis offen. Formate nicht erfinden.

## TD-I18N-01 Sprache und Ebene

- Nutzerziel: Deutsch und Englisch sowie Klartext und Fachsprache wechseln, ohne gemischte Oberfläche.
- Status: DE und EN wechseln die Beschriftung von Neu/New und zurück. Nachweis im selben Chrome-Lauf. Klartext/Fachsprache und der übrige Satzbestand sind offen. Ein englischer Migrationsfall liegt zusätzlich in `tests/test_migration_browser.py` vom Linux-Stand.

## TD-HELP-01 Hilfe und Rückweg

- Nutzerziel: Hilfe öffnen, lesen, schließen und von einem Fehler zurückkehren.
- Status: Tasten-Hilfe öffnet und schließt mit Escape. Nachweis im selben Chrome-Lauf. Ob jeder Satz zur aktuellen Oberfläche passt, ist noch nicht Satz für Satz geprüft. Voice ist nicht Teil dieser Hilfe.

## TD-SEC-T01 bis T22

- Nutzerziel: die 22 Sicherheitsfälle aus GOLDENRULES Abschnitt 13.
- Status: geplant, nicht bestanden. Die lokale Testsuite beweist sie nicht. In dieser Runde keine Firmen- oder Kryptografiearchitektur bauen, nur um einen Status grün zu färben.

## TD-LAYOUT-01 Schreibtisch im Fenster

- Nutzerziel: den offenen Thread ohne Seitenlaufleiste bedienen.
- Status: gemessen. Bei 1440×900 scrollt die Seite nicht (`page`, `notes` und `side` ohne Überlauf im kurzen Thread). Eine innere Laufleiste erscheint, wenn Verlauf oder Seitenspalte höher sind als das Fenster. Das ist die vorhandene Spaltenscrollung, kein Seitenfehler. Offen bleibt, ob bei vollem Inhalt eine wichtige Schaltfläche nur durch Scrollen erreichbar ist.

## TD-VOICE-01 und TD-NATIVE-01

- Nutzerziel: gesprochene Hilfe sowie Installation auf Mac, Windows und Linux.
- Status: zurückgestellt bis die Browser-Abnahme steht. Der Desktop-Workflow startet native Builds bei einem Pull Request, der `src/`, `packaging/`, `scripts/`, `brand/` oder `pyproject.toml` ändert, und bei einem solchen Push auf `main`. Deshalb bleibt dieser Branch lokal, bis die Browser-Runde einen eigenen, bewussten Bauauftrag hat.

## Gestrichen oder verschoben

- Vollsuite nur wegen eines neuen Planttexts wiederholen: verschoben. Der Linux-Nachweis am Reparaturcommit bleibt gültig, bis dieser Branch den Code darüber hinaus ändert. Gezielte Prüfung zuerst.
- Zweiter Orchestrator und Modellaufruf für jede triviale Auswahl: gestrichen. Der kleine Whiteboard-Hook bleibt die geplante Ergänzung aus Abschnitt 17, noch nicht implementiert.
- Native Builds jetzt: verschoben, Grund ist die Reihenfolge in Abschnitt 16 und der Workflow-Auslöser oben.
- Konkurrenzdatei zu GOLDENRULES: nicht angelegt.
