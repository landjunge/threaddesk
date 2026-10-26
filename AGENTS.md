# Arbeitsregeln


## Kira: Pflichtreferenz vor Planerstellung
Nach jedem Brainstorming und VOR jedem Plan für andere KIs die lebende Referenz /Users/landjunge/.threaddesk/Workflow/Workflow-Planerstellung-fuer-andere-KIs.md lesen und anwenden. Noch nicht abgeschlossen: neue Erfahrungen ergänzen, nicht jedes Mal neu erfinden. Fehlt Zugriff, offen melden; nicht behaupten gelesen zu haben.

## Dauerhafte Regel für Kira: Rückmeldefrist
Gilt grundsätzlich für alle künftigen delegierten Aufgaben, nicht nur den aktuellen Ablauf: höchstens 60 Sekunden ohne auftragsbezogene Rückmeldung, dann im Whiteboard nachhaken. Jeder neue Ping setzt die Frist zurück. Pro gestartetem Auftrag einen tatsächlichen Timer einrichten und dessen Start bestätigen; die Regel allein ist kein laufender Timer. Keine zeitliche Beschränkung der Geltung.


## Lokale Projektkopien und Arbeitsstände (2026-10-14)

- Vorhandene geeignete Arbeitsstände wiederverwenden. Vor neuen Kopien zuerst `git worktree list` und den jeweiligen Arbeitsstatus prüfen.
- Neue Worktrees nur bei begründetem Bedarf unter `/Users/landjunge/threaddesk-worktrees/<aufgabe>` anlegen; keine neuen Projekt-Geschwisterordner unter `/Users/landjunge` und keinen Sammelordner `Projekte`.
- Getrennte Entwicklungsstände nicht ungeprüft zusammenführen. Lokale Commits, gestagte/ungestagte Änderungen sowie einzigartige ignorierte und unversionierte Dateien vor einer Bereinigung sichern.
- Nach Abschluss entbehrliche temporäre Arbeitsstände sicher bereinigen: tatsächliche Nutzung und Pfadabhängigkeiten prüfen, normale Dateien zunächst in den macOS-Papierkorb verschieben, Git-Verknüpfungen mit der verfügbaren Git-Version fachgerecht behandeln und die Wiederherstellung dokumentieren. Keine erzwungenen Resets oder pauschalen Löschbefehle.
- Laufende Anwendungen, aktive KI-Aufträge und konfigurierte Runner-Pfade erhalten; nur konkret blockierte Einzelfälle zurückstellen. Bei notwendigen Verschiebungen Startpfade und lokale Installationsverweise reparieren und prüfen.
- Diese Regeln sind Projektanweisungen. Es wurde keine globale automatische Durchsetzung eingerichtet.


## Verbindliche Arbeitsweise ab 26. Oktober 2026

- Nutzerauftrag: Planung und Implementierung ausschließlich für ThreadDesk. KiraBridge ist vorhandene Gegenstelle; keine KiraBridge-Baupakete und keine Änderungen an dessen Codebasis. Externe Vertragsgrenzen konkret nachweisen und als Abhängigkeit ausweisen.
- Bei ThreadDesk-Arbeiten immer im Team arbeiten: echte getrennte Teilaufträge mit bestätigter Übernahme, Dateieigentum, Rückmeldungen und unabhängiger Prüfung. Keine nur behauptete Teamarbeit.
- Abgeschlossene Änderungen committen, pushen und nach bestandenem Review sowie den geltenden Pflichtprüfungen regulär nach main mergen. Keine Drafts als fertigen integrierten Stand ausgeben; keine Gates umgehen. Die Mergeautorisierung gilt für den angeforderten ThreadDesk-Umfang dauerhaft.
- Desktop und Git aktuell halten. Laufzeitänderungen aus dem final integrierten Quellpin bauen, prüfen und in der installierten Desktop-App belegen; Quell-/Paket-/Runtimeidentität und Datenerhalt dokumentieren. Eine Dokumentationsänderung erfordert keinen unveränderten Binärneubau: stattdessen nachweisen, dass der paketierte Laufzeitcode dem aktuellen Gitstand entspricht; den tatsächlichen älteren Buildpin offen nennen. Kein neues Paket aus Dokumentation behaupten.
- Vorläufiger Auftrag ist zunächst ein konkreter konsolidierter Plan aus den vorhandenen Brainstormings; geplante Funktionen nicht vorzeitig implementieren oder als fertig ausgeben. Für spätere Umsetzung immer die letzte ausdrückliche Aufgabenfreigabe beachten.
- Vollständige Bedienbarkeit durch ChatGPT über KiraBridge ist ein Abnahmeziel für alle ThreadDesk-Fachaktionen. Ein nur lesender Katalog genügt nicht. Tatsächliche verfügbare Transportwege und pro Funktion Erfolg, Konflikt, Wiederholung und Readback nachweisen.
- Verbesserte Graphansicht: echte Dateiänderungen und bewusst ausgelöste Dateizugriffe getrennt erfassen; Graphöffnung, technischer Cache/Index/Sync und bloße Statusänderungen sind keine Dateiaktivität. Quellen und offene Brainstormingentscheidungen erhalten.
- Papierkorb muss Threads und Graphbeziehungen mit stabilen IDs wiederherstellen; endgültige Löschung benötigt einen konkreten ausdrücklichen Löschauftrag. Originaldateien und geteilte Inhalte nicht pauschal kaskadieren.

## Bibliotheksauftrag mit sofortiger Integration

Der anschließende Nutzerauftrag autorisiert die schrittweise Umsetzung von Bibliotheksimport, verbindlicher lokaler Indexsuche, Dateimanager im vorhandenen Graphen, Formatadaptern und zugehöriger Dateiwiederherstellung. Der bisherige Plan wird erweitert, kein konkurrierender Plan angelegt. Jedes fertige Paket braucht sofort einen tatsächlichen KiraBridge-Aufruf mit Readback; keine spätere Sammelintegration und keine Erfolgsaussage allein aus Mock-/Unit-Tests. KiraBridge selbst bleibt unverändert. Fehlende Originalbytes, native Vertragsgrenzen und nicht geprüfte Principal-Kontexte ausdrücklich benennen. Indexsuche ist nun hohe Priorität und verbindlicher Umfang.
