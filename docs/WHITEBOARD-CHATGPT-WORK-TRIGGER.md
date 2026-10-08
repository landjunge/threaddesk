# Optionaler Whiteboard-Trigger für ChatGPT Work

`scripts/whiteboard_work_trigger.py` ist ein **nicht aktivierter, opt-in
Brückenkopf** zur Workspace Agents API. Er kann einen veröffentlichten ChatGPT
Workspace Agent aus einem serverseitigen Ablauf anstoßen. Er setzt weder diese
ChatGPT-Unterhaltung fort noch weckt er Voice oder eine laufende ChatGPT-Sitzung.
Die angenommene Übergabe erscheint in einer separaten Work-Agent-Konversation.

Die offizielle Dokumentation beschreibt den festen Endpunkt
`POST https://api.chatgpt.com/v1/workspace_agents/{agtch_ID}/trigger`, den
optionalen `Idempotency-Key` und `202 Accepted` als dauerhaft eingereihten
Trigger. Eine Agentenantwort ist über diese API nicht abrufbar:

- <https://developers.openai.com/workspace-agents/trigger-runs>
- <https://developers.openai.com/workspace-agents/authentication>

## Grenzen und Voraussetzungen

Vor einer echten Nutzung muss der Account-Inhaber bzw. Workspace-Admin:

1. Workspace Agents freigeben und einen Agenten über den API-Kanal
   veröffentlichen; dessen Trigger-ID hat das Format `agtch_...`.
2. persönliche Access Tokens in den Workspace-Rechten erlauben und einen Token
   mit dem Scope **Workspace Agents** erstellen.
3. diesen Token bewusst als eigenen macOS-Keychain-Eintrag provisionieren.

Der Standard-Keychain-Service ist
`de.netzwerkpunkt.threaddesk.workspace-agent`, der Accountname ist exakt die
`agtch_...`-ID. Das Programm durchsucht keine anderen Einträge und unterstützt
bewusst weder Platform API Keys noch Token in Argumenten, Umgebungsvariablen,
Plists oder Zustandsdateien. Zur Provisionierung die macOS-App
**Schlüsselbundverwaltung** verwenden; den Token nicht in Shell-Verlauf oder
Dokumentation kopieren.

Dieser Code installiert keinen Timer und ändert keine globale Konfiguration.
Der bestehende lokale 15-Sekunden-Relay bleibt unverändert. In der Entwicklung
und den Tests wurde kein echter Workspace-Agent-Aufruf ausgeführt.

## Welche Einträge übertragen werden

Der Trigger verwendet direkt den Filter des lokalen Terminal-Relays. Zulässig
sind nur:

- `result` oder `problem` von `actor_type=codex`, oder
- `problem` von `actor_type=system` mit `metadata.runner=codex-v1`,

wenn im append-only Verlauf zeitlich vorher ein `task` von
`actor_type=chatgpt` mit derselben `task_id` und
`metadata.runner=codex-v1` steht. Eine spätere Wiederverwendung derselben
`task_id` autorisiert keinen älteren Abschluss rückwirkend.

Die API verlangt ein Textfeld `input`. Darin liegt ausschließlich ein kompakt
JSON-codiertes Objekt mit Schema, `task_id`, Quell-`entry_id` und
`entry_type`. Eine Commit-SHA und die explizit konfigurierte Repo-Referenz werden
nur bei `push_verified=true` und einer gültigen 40-stelligen SHA ergänzt. Eine
Report-Referenz wird nur mit `report_verified=true` übernommen. Whiteboard-Text,
Historie, Schlüssel, Header, neue Aufträge oder Cloud-Freigaben werden nie in
dieses Objekt kopiert.

## Sicherer Start

Die Beispiele verwenden nur Platzhalter. Zuerst wird eine historische Baseline
angelegt; vorhandene Abschlüsse werden dadurch nicht nachträglich gesendet:

```sh
PYTHONPATH=src .venv/bin/python scripts/whiteboard_work_trigger.py bootstrap \
  --root /path/to/thread-desk-data \
  --thread THREAD_ID \
  --state /private/path/work-trigger-state.json
```

Ein Dry-run entdeckt danach neue zulässige Einträge und persistiert sie als
`pending`, liest aber keinen Keychain-Token und öffnet keine Netzwerkverbindung:

```sh
PYTHONPATH=src .venv/bin/python scripts/whiteboard_work_trigger.py once \
  --root /path/to/thread-desk-data \
  --thread THREAD_ID \
  --state /private/path/work-trigger-state.json \
  --channel-id agtch_PUBLISHED_CHANNEL \
  --conversation-key threaddesk:THREAD_ID \
  --repo-ref owner/repository@refs/heads/feature \
  --dry-run
```

Erst nach Admin-Freigabe, veröffentlichter Kanal-ID, separater
Token-Provisionierung und bewusster Aktivierung darf derselbe `once`-Aufruf ohne
`--dry-run` verwendet werden. Es gibt keine frei konfigurierbare Ziel-URL. Eine
echte Ausführung liest ausschließlich den genannten Keychain-Eintrag und sendet
an `api.chatgpt.com`.

Der lokale Zustand lässt sich ohne Tokenzugriff prüfen:

```sh
PYTHONPATH=src .venv/bin/python scripts/whiteboard_work_trigger.py status \
  --root /path/to/thread-desk-data \
  --thread THREAD_ID \
  --state /private/path/work-trigger-state.json
```

## Zustände und Wiederholung

- `pending`: lokal dauerhaft entdeckt, aber wegen Dry-run oder fehlender
  Konfiguration nicht gesendet.
- `error`: Versuch fehlgeschlagen oder Antwort war nicht exakt ein `202` mit
  vertrauenswürdiger `https://chatgpt.com/c/...`-URL. Der nächste Lauf versucht
  dieselbe Quelle mit demselben Idempotency-Key erneut.
- `accepted`: OpenAI hat das Ereignis angenommen und dauerhaft eingereiht. Das
  bedeutet **nicht**, dass der Agent fertig ist, Kira entschieden hat oder diese
  ChatGPT-Sitzung den Inhalt gelesen hat.

State-Schreiben erfolgt unter Dateisperre und atomar nach jeder Entdeckung und
jedem Versuch. Nach einem Crash darf derselbe externe Trigger wegen des stabilen
Idempotency-Key sicher wiederholt werden. Bereits als `accepted` gespeicherte
Quellen werden nach Neustart nicht erneut gesendet. Token und rohe
Fehlerantworten werden weder gespeichert noch ausgegeben.
