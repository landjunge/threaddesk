# Whiteboard alle fünf Minuten lesen

Der lokale Wecker liest ein ausgewähltes JSON-Whiteboard mit macOS launchd alle
300 Sekunden. Beim Anmelden startet er erneut. Während der Mac schläft oder
abgemeldet ist, gibt es keinen garantierten Fünf-Minuten-Takt.

Er liest ausschließlich. Whiteboard-Inhalte werden weder ausgeführt noch als
Agentenaufträge übernommen. Der Status enthält IDs, Hashes, Zeit und Anzahl,
keine zweite Kopie der Texte. Bei neuen/geänderten Einträgen wird eine feste
macOS-Mitteilung versucht. `notification: submitted` bedeutet nur, dass macOS
den Aufruf angenommen hat, nicht, dass jemand ihn gesehen hat.

**Dieser Wecker weckt keine ruhenden Grok-, Claude- oder ChatGPT-Sitzungen.**
`agent_delivery: not_connected` hält diese Grenze ausdrücklich fest. Eine
Empfangsbestätigung muss vom jeweiligen Agenten selbst kommen.

## Bedienung

Im Repository mit einem vorhandenen Python 3.8 oder neuer:

```sh
python3 scripts/whiteboard_watch.py install --thread THREAD_ID
python3 scripts/whiteboard_watch.py status --thread THREAD_ID
python3 scripts/whiteboard_watch.py uninstall --thread THREAD_ID
```

`--root` wählt beim Installieren den vorhandenen Arbeitsbereich; Vorgabe ist
`~/.threaddesk`. Der ausgewählte Pfad bleibt gebunden. Beim Wechsel des
ThreadDesk-Arbeitsbereichs den Wecker bewusst umstellen. Andere Speicherformen
wie SQLite werden nicht als JSON gelesen.

Installation und Status liegen unter
`~/Library/Application Support/ThreadDesk/whiteboard-watch/THREAD_ID/`.
Der LaunchAgent liegt unter `~/Library/LaunchAgents/` und trägt den Namen
`de.netzwerkpunkt.threaddesk.whiteboard.THREAD_ID.plist`.
Zum Prüfen `launchctl print gui/$(id -u)/de.netzwerkpunkt.threaddesk.whiteboard.THREAD_ID`.
Deinstallation stoppt den Timer und entfernt seinen LaunchAgent. Der zuletzt
gelesene Status bleibt erhalten. Für einen Test ohne Installation:

```sh
python3 scripts/whiteboard_watch.py once --root TEST_ROOT --thread THREAD_ID --state /tmp/wb-status.json
python3 -m pytest -q tests/test_whiteboard_watch.py
```

Fehlerhafte Dateien verhindern einen Fortschritt des Lesestands. Änderungen
an bestehenden IDs werden erkannt. Alte/neue Zeitstempel und Ordnungszahlen
entscheiden nicht darüber, ob ein Eintrag neu ist. Nach einem Neustart werden
bekannte Einträge nicht erneut als neu gemeldet. Fehlgeschlagene Mitteilungen
bleiben für den nächsten Versuch vorgemerkt.
