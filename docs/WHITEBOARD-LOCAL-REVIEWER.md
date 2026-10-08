# Lokaler Whiteboard-Reviewer

Der lokale Reviewer prüft neue Abschlüsse des bereits vorhandenen
Whiteboard-Codex-Runners. Er ist eine neue, kurzlebige Codex-Sitzung und nicht
Kira beziehungsweise die laufende ChatGPT-Konversation. Sein Ergebnis ist nur
eine Empfehlung.

## Feste Grenzen

- Whiteboard: bei der Installation fest gebundener lokaler Thread.
- Zielrepository: ausschließlich
  `/Users/landjunge/agent-authority-lab-wb-runner`. Whiteboard-Inhalt kann weder
  Repository noch Branch oder Shellparameter verändern.
- Modell: `gpt-5.6-sol`, Reasoning Effort `medium`.
- Codex: Sandbox `read-only`, Approval `never`, Multi-Agent aus, Websuche aus,
  keine zusätzlichen Schreibverzeichnisse. Die Sitzung ist ephemeral und lädt
  keine persönliche Codex-Konfiguration. Ein lokaler Profiltest blockierte für
  diesen Sandbox-Prozess einen `curl`-Aufruf bereits bei der DNS-Auflösung,
  während derselbe Host außerhalb der Sandbox erreichbar war. Das belegt die
  Netzwerkgrenze dieses getesteten Profils, aber keine absolute Sperre aller
  denkbaren Prozess- oder Trafficwege; der Runner setzt deshalb kein nicht
  belegtes `sandbox_read_only.network_access`-Feld.
- Höchstens ein Reviewer-Prozess gleichzeitig, höchstens 300 Sekunden
  einschließlich Unterprozessen und höchstens drei neu gestartete Reviews pro
  Europe/Berlin-Kalendertag. Das ist ein Nutzungslimit, kein Geld-Hardcap.
- Kein automatischer Retry nach Start. Ein Crash, Timeout, ungültiges JSON oder
  unerwartetes Feld endet fail-closed als `failed` und kostet für dieselbe Quelle
  keinen zweiten automatischen Modellstart. Nach einem erkannten harten Crash
  wechselt der Runner zusätzlich auf `halted`, weil ein verwaister Prozess nicht
  sicher von einer wiederverwendeten PID unterschieden werden kann; weitere
  automatische Starts bleiben dann aus.
- Bei Installation werden alle bereits vorhandenen geeigneten Quellen als
  `baselined` gespeichert. Alte Whiteboard-Aufträge werden nicht wiederholt.

Als Quelle gelten nur nach einer autorisierten
`task/chatgpt/metadata.runner=codex-v1`-Aufgabe angehängte terminale
`result|problem`-Einträge von Codex oder ein markiertes System-`problem`.
Task-ID, Reihenfolge und – falls durch die Aufgabe vorgegeben – Run-ID müssen
passen. Zusätzlich muss die vom bestehenden Runner erzeugte Run-ID die konkrete
Task-Eintrags-ID binden (`codex-<task-entry-id>-<nonce>`). Ein später
unautorisierter Task mit wiederverwendeter Task-ID entzieht die Bindung.
Reviewer-Notizen können den Reviewer nicht erneut auslösen.

## Datenfluss und Whiteboard-Vertrag

Der Modellprozess erhält keine Whiteboard-Historie und keinen Quelltext eines
Eintrags. Die feste Instruktion enthält nur eine kleine JSON-Allowlist:
Quell-ID, Typ, Task-ID, Run-ID, eine syntaktisch gültige Commit-SHA samt
`push_verified` und gegebenenfalls einen begrenzten maschinenlesbaren
Reason-Code. Dadurch werden freier Prompttext, Shellfragmente und mögliche
Geheimnisse nicht weitergereicht.

Die Modellantwort muss exakt die Felder `status`, `summary`, `evidence`,
`reservations` und `recommendation` erfüllen. Erlaubte Status sind `reviewed`
und `inconclusive`; Längen und Anzahl werden nochmals deterministisch geprüft.
Nur danach hängt der Wrapper genau einen Eintrag an:

- `entry_type=note`, `actor_type=codex`, `actor=Lokaler Reviewer`
- `metadata.role=reviewer`, `recommendation_only=true`
- `chatgpt_received=false`, `source_entry_id`, `reviewer_status`
- `external_key=wb-local-review:<source-id>:v1`

Der Codex-Prozess selbst erhält keinen schreibbaren Whiteboard-Pfad. Er darf
keine Aufgabe, Entscheidung, Übernahme, Freigabe oder Umsetzung erzeugen.

## Betrieb

Installation erfolgt erst nach grünen Tests mit dem gebundenen Python 3.9 oder
neuer. Das folgende Beispiel ist für den vorgesehenen Thread vollständig:

```sh
PYTHONPATH=src /Users/landjunge/threaddesk/.venv/bin/python \
  scripts/whiteboard_local_reviewer.py install \
  --root /Users/landjunge/.threaddesk \
  --thread da961e772739 \
  --repo /Users/landjunge/agent-authority-lab-wb-runner
```

Der Installer legt den User-Agent
`de.netzwerkpunkt.threaddesk.local-reviewer.da961e772739` mit einem Intervall
von 15 Sekunden an. Private Zustände liegen unter
`~/Library/Application Support/ThreadDesk/whiteboard-local-reviewer/`:
Verzeichnis `0700`, atomare JSON-Datei und Lock `0600`. Das Tagesbudget wird
vor dem Spawn atomar reserviert.

Status und ein manueller einzelner Poll (der bei einer neuen Quelle einen echten
Modellaufruf auslösen kann):

```sh
PYTHONPATH=src /Users/landjunge/threaddesk/.venv/bin/python \
  scripts/whiteboard_local_reviewer.py status --thread da961e772739

PYTHONPATH=src /Users/landjunge/threaddesk/.venv/bin/python \
  scripts/whiteboard_local_reviewer.py once --thread da961e772739
```

Deinstallation stoppt nur diesen User-Agent und bewahrt den privaten State, um
historische Quellen bei einer späteren bewussten Neuinstallation weiterhin zu
erkennen:

```sh
PYTHONPATH=src /Users/landjunge/threaddesk/.venv/bin/python \
  scripts/whiteboard_local_reviewer.py uninstall --thread da961e772739
```

Der bestehende Whiteboard-Codex-Runner und der Terminal-Relay werden dabei
weder verändert noch gestoppt.

## Verifikationsprotokoll

Vor Installation werden ausschließlich Fake-Executors verwendet; dadurch gibt
es keinen Modellcall und keine Modellkosten. Der gezielte Testlauf umfasst:

1. Baseline alter Quellen, neue autorisierte Quelle genau einmal und Restart.
2. Unautorisierte, verspätete oder falsch gebundene Task-ID/Run-ID.
3. Tageslimit drei, Einzellock und persistente Crash-/Timeout-Fehler.
4. Ungültiges oder zu großes JSON sowie unerwartete Felder.
5. Fester Listenaufruf ohne Shell, kein freier WB-Text im Prompt und keine
   Rückkopplung aus Reviewer-Notizen.
6. launchd-Vertrag, private Dateirechte und exakter installierter Scriptinhalt.

Nach dem Testlauf werden Commit, normaler Push und `git ls-remote` verglichen.
Die Live-Abnahme prüft anschließend Agent-Registrierung, `status=idle`,
`baseline_count`, Dateirechte und Gleichheit der installierten Datei mit der
getesteten Commit-Version. Dabei wird kein Fake-Auftrag ins produktive
Whiteboard geschrieben und kein historischer Auftrag gestartet.
