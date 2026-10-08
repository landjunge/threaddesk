# ThreadDesk terminal result relay (local macOS)

Ein kleiner, separater 15-Sekunden-Wächter für den bestehenden ThreadDesk-JSON-Whiteboard-Thread.

- Liest über `JsonStore` nur `result`/`problem` von Codex sowie `problem` des ausdrücklich markierten `codex-v1`-Runners.
- Einträge zählen nur, wenn ein passender vorheriger Auftrag `task/chatgpt/runner=codex-v1` existiert.
- Fügt pro Quell-Entry-ID genau eine append-only `note` mit `handoff_to=Kira` und `handoff_state=pending_review` an. Die feste `external_key` verhindert Doppelung nach Neustart.
- Sendet eine lokale macOS-Mitteilung ohne Whiteboard-Text im ausführbaren AppleScript.
- Legt eine persistente Baseline historischer Abschluss-Einträge an; ein gezielter aktueller Task lässt sich beim Einrichten ausnehmen.
- Startet **keine** Modelle, führt **keine** Whiteboard-Inhalte aus und bestätigt **keine** ChatGPT-Übernahme.
- Eine vom Betriebssystem angenommene Desktop-Mitteilung ist keine garantierte Anzeige auf iOS.
- **Kein Weg in einen laufenden ChatGPT-Chat:** Für eine ChatGPT-Benachrichtigung bleibt eine getrennte, maximal stündliche Watch als Rückfallweg nötig.

Live-Installation (08.10.2026): `de.netzwerkpunkt.threaddesk.terminal-relay.da961e772739`, über launchd alle 15 Sekunden. Laufzeitkopie unter `~/Library/Application Support/ThreadDesk/whiteboard-terminal-relay/da961e772739/`; der angepinnte Interpreter ist die vorhandene ThreadDesk-Venv, `THREADDESK_SOURCE_ROOT` zeigt auf den vorhandenen ThreadDesk-Quellpfad. Bootstrap hat historische Abschlüsse ausgeklammert und den Blocker des C1–C7-Auftrags einmalig vorgemerkt.

Die aktive Agent-Authority-Arbeit wird durch diesen Wächter nicht wiederaufgenommen; er reicht nur belegte Zustände an den Whiteboard-Prüfposteingang weiter.
