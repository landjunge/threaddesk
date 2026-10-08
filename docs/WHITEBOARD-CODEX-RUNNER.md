# Whiteboard-Codex-Runner MVP v1

Der Runner verbindet genau einen lokalen ThreadDesk-Whiteboard-Thread mit genau
einem vorhandenen Git-Repository. Er ist kein allgemeiner Dispatcher: Zu einer
Zeit läuft höchstens ein Terminal-Codex, und nur ausdrücklich markierte Tasks
werden berücksichtigt.

## Startberechtigung

Ein Eintrag ist nur startbar, wenn alle drei Werte exakt passen:

```json
{
  "entry_type": "task",
  "actor_type": "chatgpt",
  "metadata": {
    "runner": "codex-v1"
  }
}
```

Außerdem braucht der Eintrag eine `task_id`. Der beim Start gebundene Thread und
Repository-Pfad kommen ausschließlich aus der Runner-Konfiguration. Text oder
Metadaten des Tasks können das Repository nicht wechseln. Eine eigene Zeile
`STOP` im Task verhindert den Start und wird als persistenter Zustand `stopped`
festgehalten.

Der Tasktext wird weder in einen Shell-Befehl interpoliert noch als
Kommandozeilenargument übergeben. Der Bootstrap nennt nur Thread, Entry-ID,
Whiteboard-Root, gebundenes Repo und Run-ID sowie feste Arbeitsregeln. Codex liest
den Task anschließend selbst über `JsonStore` und den ThreadDesk-Service.

## Einmaliger manueller Lauf

Aus einem ThreadDesk-Checkout mit Python 3.9 oder neuer:

```sh
PYTHONPATH=src python3 scripts/whiteboard_codex_runner.py once \
  --root /Users/name/.threaddesk \
  --thread THREAD_ID \
  --repo /absoluter/pfad/zum/zielrepo \
  --model gpt-5.6-sol \
  --reasoning-effort high
```

`--repo` muss der Wurzelpfad eines vorhandenen Git-Repositories sein. Der Runner
verlangt einen benannten aktuellen Branch und prüft nach dem Lauf, dass Codex ihn
nicht gewechselt oder detached hat. Eine Abweichung endet als `blocked`. Der Runner
ruft Codex ohne Shell mit festen Optionen auf:

```text
codex -a never --sandbox workspace-write \
  --model gpt-5.6-sol \
  -c 'model_reasoning_effort="high"' \
  -c sandbox_workspace_write.network_access=true \
  -c features.multi_agent=false \
  -C GEBUNDENES_REPO --add-dir WHITEBOARD_ROOT exec --color never -
```

Codex bekommt damit Schreibzugriff auf das gebundene Repo und den Whiteboard-Root
sowie aus dem `workspace-write`-Sandboxmodus heraus Netzwerkzugriff für den
verlangten Git-Push. `danger-full-access` wird nicht verwendet. Modell und
Reasoning-Effort sind pro Runner-Bindung explizit konfigurierbar; die Vorgaben
dieser Installation sind `gpt-5.6-sol` und `high`. Der Runner setzt sie nur per
Prozessargument und verändert niemals `~/.codex/config`.
Der Bootstrap verbietet Repo- und Branchwechsel, Merge, Force-Push, Secrets und
weitere Agenten.

## Installation unter macOS

```sh
PYTHONPATH=src python3 scripts/whiteboard_codex_runner.py install \
  --root /Users/name/.threaddesk \
  --thread THREAD_ID \
  --repo /absoluter/pfad/zum/zielrepo \
  --model gpt-5.6-sol \
  --reasoning-effort high
```

Die Installation validiert Thread, Git-Root und Codex-Executable, kopiert das
Runner-Script in `~/Library/Application Support/ThreadDesk/` und registriert
einen benutzergebundenen launchd-Job. Der Job prüft alle 15 Sekunden. Ein
laufender `once`-Prozess hält einen exklusiven Lock, sodass ein weiterer Tick
keinen zweiten Agenten starten kann.

Der launchd-Job bindet den vollständig aufgelösten `sys.executable` und den
`src`-Pfad des Checkouts, aus dem `install` ausgeführt wurde; er verlässt sich
nicht auf ein unbestimmtes `python3` aus launchds `PATH`. Der Installer lehnt
Python älter als 3.9 mit einer klaren Fehlermeldung ab. Interpreter und Checkout
müssen deshalb verfügbar bleiben.

Deinstallation erhält Status und Laufprotokolle:

```sh
PYTHONPATH=src python3 scripts/whiteboard_codex_runner.py uninstall \
  --thread THREAD_ID \
  --repo /absoluter/pfad/zum/zielrepo
```

## Status und persistenter Schutz gegen Doppelstarts

```sh
PYTHONPATH=src python3 scripts/whiteboard_codex_runner.py status \
  --root /Users/name/.threaddesk \
  --thread THREAD_ID \
  --repo /absoluter/pfad/zum/zielrepo \
  --model gpt-5.6-sol \
  --reasoning-effort high
```

Der Status liegt standardmäßig bindungsspezifisch unter
`~/Library/Application Support/ThreadDesk/whiteboard-codex-runner/`. Er enthält
für jede verarbeitete Entry-ID die Run-ID und einen terminalen oder laufenden
Zustand. Gültige Zustände sind:

- `idle`: kein startbarer Task gefunden;
- `running`: genau ein Codex-Prozess ist zugeordnet;
- `done`: gültiges `result` mit allen Erfolgsbelegen;
- `blocked`: `problem`, Prozessfehler oder unzureichender Abschlussbeleg;
- `stopped`: eigenständige `STOP`-Zeile wurde beachtet;
- `busy`: ein anderer Runner-Prozess hält den Lock.

Ein als `running`, `done`, `blocked` oder `stopped` registrierter Entry wird nach
einem Neustart nicht erneut gestartet. Bleibt nach einem Runner-Abbruch ein
zugeordneter Codex-Prozess nachweislich aktiv, startet der nächste Tick ebenfalls
keinen zweiten. Ein verwaister Lauf ohne Prozess und ohne Terminaleintrag wird
append-only als `problem` beendet.

## Whiteboard-Rückkanal und Abschluss

Codex muss für dieselbe `task_id` und `run_id` zuerst `claimed` schreiben, nach
jedem erfolgreichen Planpunkt `progress`, bei einem Blocker `problem` und am
Ende `result`. Alle Einträge werden über
`threaddesk.services.whiteboard.append` mit `JsonStore` angehängt; vorhandene
Whiteboard-Dateien bleiben unverändert.

Ein Prozess-Exitcode 0 ist kein Erfolg. `done` verlangt zusätzlich:

1. einen `claimed`-Eintrag von `actor_type=codex`;
2. einen `result`-Eintrag für Task- und Run-ID;
3. `metadata.commit_sha` als 7- bis 40-stellige Git-SHA;
4. `metadata.push_verified` mit dem booleschen Wert `true`.

Fehlt einer dieser Belege, schreibt der Runner einen append-only
`problem`-Eintrag und setzt den Task auf `blocked`. Laufprotokolle enthalten die
Codex-Standardausgabe und liegen mit Dateimodus `0600` neben dem Status.

## 60-Sekunden-Regel

Der laufende Runner prüft `claimed`, `progress`, `problem` und `result` derselben
Task-/Run-ID. Jeder neue Codex-Eintrag setzt die Frist zurück. Bleibt ein Ping 60
Sekunden aus, schreibt der Runner `problem`, beendet den Codex-Prozess fail-closed
und markiert den Task `blocked`. Ein Terminaleintrag erhält 30 Sekunden zum
geordneten Prozessende.

Dieser Timer überwacht nur den lokalen Lauf. Er weckt keine Voice-Sitzung und
behauptet keine aktive Zustellung an Chat oder Mobilgerät.

## Grenzen des MVP

- Ein Runner bindet einen Thread, ein Repo und einen aktiven Agenten. Es gibt
  keinen Multi-Agent-Dispatcher, keine parallele Queue, kein Grok und keine UI.
- Autorisierung ist die lokale, exakte Task-Markierung. Der MVP ergänzt keine
  Personen-, Geräte- oder kryptografische Firmenidentität.
- Wegen `--add-dir WHITEBOARD_ROOT` kann der Codex-Sandboxprozess technisch auf
  diesen Root schreiben. Die Service-only-/append-only-Regel wird durch den
  Bootstrap und die Abschlussprüfung verlangt, aber in diesem MVP nicht durch
  eine separate Dateisystem-Proxygrenze erzwungen.
- Der Runner prüft einen strukturierten Push-Beleg, führt aber keine Signatur-
  oder Remote-Identitätsprüfung durch. Codex muss den Push selbst verifizieren.
- launchd-Installation ist macOS-spezifisch. `once` und `status` setzen ein
  POSIX-System mit `flock` voraus.
- Es gibt keinen automatischen Merge und keinen Force-Push-Fallback.
