# ThreadDesk 0.1.2 (Tauri, Intel macOS)

Dieser Veröffentlichungskandidat bündelt den vorhandenen lokalen
ThreadDesk-Python-HTTP-Server mit einem eigenständigen Tauri-WebKit-Fenster.
Auf dem Zielrechner ist keine eigene Pythoninstallation erforderlich.

Das Fenster öffnet den vorhandenen Arbeitsbereich unter `~/.threaddesk`.
Es legt keine zweite Ablage an und migriert keine bestehende. Es gibt weder
einen automatischen Aktualisierungsendpunkt noch einen entfernten Dienst.
Version 0.1.2 ist ausschließlich ad-hoc signiert.

Auf einem x86_64-Mac bauen:

1. Die ThreadDesk-Entwicklungsabhängigkeiten einschließlich PyInstaller installieren.
2. Im Repository-Stamm `python -m PyInstaller --clean --noconfirm --distpath packaging/tauri/backend/dist --workpath packaging/tauri/backend/build packaging/tauri/backend/ThreadDeskServer.spec` ausführen.
3. `packaging/tauri/backend/dist/ThreadDeskServer --self-test` ausführen.
4. Unter `packaging/tauri` erst `npm ci`, dann `npm run build` ausführen.
5. `src-tauri/target/release/bundle/macos/ThreadDesk.app` prüfen, bei Bedarf lokal mit `codesign --force --deep --sign -` signieren und für einen GitHub-Release als ZIP verpacken.

Eine Signatur mit Apple Developer ID oder eine Notarisierung wird nicht
bereitgestellt. Gatekeeper kann eine manuelle Benutzerfreigabe verlangen.
Vor Weitergabe das Bundle, den gebündelten Hintergrunddienst und die lokale
Oberfläche mit einem sauberen Testarbeitsbereich prüfen. Dies ist ein
Veröffentlichungskandidat, keine notarisierte stabile Ausgabe.

## Sichtbare Version und Quellidentität

Die gemeinsame Kopfzeile zeigt Paketversion und die ersten sieben Zeichen
des Quellcommits. Beide PyInstaller-Spezifikationen führen vor dem Einsammeln
der Ressourcen `scripts/write_build_info.py` aus. Das Skript hält aktuellen
Commit, lokale Änderungen und UTC-Baukennung in einer ignorierten
Paketressource fest. Die laufende Anwendung liest diese Ressource, ohne Git
auszuführen oder auf einen Nutzerarbeitsbereich zuzugreifen.

Die gewünschte Quelle vor dem Bau eines weiterzugebenden Pakets committen.
Ein sauberer Arbeitsstand erzeugt eine Kennzeichnung wie `v0.1.2 · abcdef0`;
ein nicht committeter Stand ergänzt `+lokal`. Ein Quellstart ohne gültige
Paketmetadaten zeigt `Quellstand` statt einer behaupteten Commitkennung.
Bei Versionsänderungen Pythonpaket, Tauri-Konfiguration, npm- und Cargo-Paket
auf demselben Stand halten.

Vor dem Austausch einer Installation die vorherige App und den Arbeitsbereich
erhalten, den Paket-Selbsttest ausführen und die App mit einem gesonderten
Benutzerverzeichnis und einer Arbeitsbereichskopie prüfen. Tatsächliche
Kopfzeile und Anzahlen der Threads, Graphobjekte und Whiteboard-Einträge prüfen,
dann Quellhashes und eingebettete Baumetadaten vergleichen. Nur das geprüfte
Bundle installieren. Die anschließende Veröffentlichung genau dieses
Quellcommits hält die installierte Kennzeichnung gegenüber GitHub nachvollziehbar.

## Reihenfolge der Arbeitsbereichsantworten

Unabhängige Bearbeitungsformulare können in anderer Reihenfolge antworten als
angefragt. Die Oberfläche unterdrückt überholte Arbeitsbereichsantworten,
damit eine ältere Notizspeicherantwort weder eine spätere Wiederherstellung
eines Zwischenstands noch die Threadauswahl ersetzen kann. Anfragen werden
weiter normal abgeschlossen; Schreibfehler bleiben sichtbar. Die vorhandene
Browserprüfung verzögert eine echte Notizspeicherantwort bis nach dem
Wiederherstellungswechsel und prüft die wiederhergestellte Notiz erneut nach
einem Dienstneustart.
