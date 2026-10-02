ThreadDesk als lokale Desktop-App für Intel-Mac, Apple Silicon und Windows.

- Threads, Notizen, Zwischenstände, Wissenskarte und Whiteboards lokal bearbeiten.
- Lokales LLM über Ollama optional verwenden; Modell selbst auswählen.
- Freigegebene Whiteboard-Einträge zwischen zwei lokalen Installationen synchronisieren.
- Unter **Daten** eine Sicherung herunterladen und in einem getrennten Arbeitsbereich öffnen. Der ursprüngliche Stand bleibt erhalten; zwischen Arbeitsbereichen wechseln ist möglich.
- UI-Bibliotheken sind mitgeliefert; der App-Start benötigt kein Terminal.

Intel-Mac: **ThreadDesk-macOS.dmg**. DMG öffnen, ThreadDesk nach Programme ziehen.
Apple Silicon: **ThreadDesk-macOS-AppleSilicon.dmg**.
Windows: **ThreadDesk-Windows.exe**.

Alle Pakete enthalten Python. Für jede Datei liegen eine SHA-256-Prüfsumme und ein Herkunftsbeleg mit dem Quell-Commit bei. Veröffentlichung erfolgt erst nach vollständiger, zweimaliger Testsuite ohne übersprungene Abnahmetests sowie erfolgreichen nativen Builds und Paket-Selbsttests.

Diese Ausgabe ist ein Release-Kandidat. Der Start auf deinem konkreten Mac und die Qualität deines gewählten lokalen LLM können durch CI nicht bewiesen werden. macOS-Pakete sind ad-hoc signiert, nicht Apple-notarisiert. Team-Sync ist lokal über HTTP; ein öffentlicher Internet-Server gehört nicht zu dieser Ausgabe. Verlinkte Dateien außerhalb des Arbeitsbereichs sind nicht im Backup enthalten. Backups enthalten private Inhalte und Raum-Zugangsdaten.
