# ThreadDesk — der MVP-Plan vom 14.08.2026 (abgeschlossen, historisch)

> **Diese Datei ist ein Rückblick, keine Arbeitsanweisung.**
>
> Sie beschreibt das ursprüngliche MVP und ist damit erfüllt: Threads, Kontext,
> Switcher, Snapshot, Prompt-Generator, MCP, Grok- und Gnom-Brücke, Gate und
> Dashboard stehen.
>
> **Die Phasennummern 1 bis 5a unten gelten nicht mehr.** Die laufende Planung
> zählt anders — dort bedeutet „Phase 4" etwas völlig anderes als hier. Wer eine
> Phasennummer liest, meint die der laufenden Planung, nicht diese. Sie stehen
> hier nur, damit die Commit-Geschichte lesbar bleibt.
>
> Was heute gilt und was als Nächstes ansteht, steht nicht im Repo, sondern im
> Arbeitsstand, den der Eigentümer pflegt. Wer hier nachschlägt, um zu wissen,
> was zu tun ist, schlägt an der falschen Stelle nach.

## Ziel

Kontext und Standpunkt nicht verlieren, wenn zwischen parallelen KI-Ideen gewechselt wird.
Kein Orchestrator. Kein aufgeblähtes System.

## Name

- **Produkt / Repo:** ThreadDesk · `landjunge/threaddesk`
- PyPI-Name `threaddesk` frei
- GitHub-Name ist mehrfach belegt (fremde, leere/andere Produkte). Unser Namespace: `landjunge/threaddesk`
- Alternativen, falls der Name stört: ThreadKeep, ContextDock, PinThread

## Striktes MVP (v0.1)

1. Threads erstellen, umbenennen, archivieren, löschen
2. Persistenter, leicht strukturierter Kontext pro Thread
3. Thread-Switcher stellt den vollen Kontext wieder her
4. Snapshot speichern & laden

Alles andere kommt später: Kanban, Prompt-Generator, MCP, Grok Build, Tollgate, Dashboard.

## Erfolgskriterium

5–10 Threads anlegen, beliebig wechseln, jedes Mal in unter 2 Sekunden wieder im richtigen Kontext inkl. Snapshot.

## Architektur

```
core / storage / ui / services / api
```

- Core bleibt dumm und stabil
- UI und Storage sprechen nur über `api.ThreadService`
- Events für Wechsel und Snapshots
- Neue Features = Modul unter `services/`

## Phasen (historische Zählung, abgelöst)

| Phase | Inhalt | Ziel |
|---|---|---|
| 1 | Core + Storage + Events | Fundament |
| 2 | CLI + Switcher + Snapshot | nutzbar |
| 3 | Polish, Fehler, echte Nutzung | Alltag — fertig: Status, Notiz-Append, Dateipfade, Titel/Nummer-Switch, --yes |
| 4a | Prompt-Generator (lokal, kein Execute) | fertig |
| 4b | MCP stdio + Handoff (kein delete, untrusted wrap) | fertig |
| 4c | Grok-Build-Bridge (Paket schreiben, Grok nicht starten) | fertig |
| 4d | Tollgate-Wrap (lokales Gate, kein Produkt-Import) | fertig |
| 4e | Dashboard (nur Ansicht, HTML + Terminal) | fertig |
| 5a | Gnom-Hub-Bridge → gnom-hub-v1 (Send/Execute, kein POST) | fertig |

## Sicherheit (von Anfang an)

- Alles lokal. Keine Cloud.
- Keine API-Keys in Thread-Dateien
- ThreadDesk führt nichts aus
- MCP wrappt Notizen als `<untrusted>` und hat kein delete
- Prompt-Injection: MCP wrappt Notizen, Gate ändert sich nicht durch Notiztext
- Tollgate-Wrap ist lokal (`td gate`). Das Produkt ~/tollgate bleibt unberührt.
