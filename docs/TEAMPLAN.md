# ThreadDesk – Teamplan (Stand 14.08.2026)

## 1. Ziel

Eine schlanke, lokal-first Control-Layer, die den Pain „Kontext- und Standpunktverlust beim Wechseln zwischen parallelen KI-Ideen“ löst.
Kein Orchestrator. Kein aufgeblähtes System.

## 2. Striktes MVP (v0.1)

Nur diese vier Dinge:

- Threads erstellen, umbenennen, archivieren, löschen
- Persistenter, leicht strukturierter Kontext pro Thread
- Blitzschneller Thread-Switcher (stellt den vollen Kontext wieder her)
- Snapshot speichern & laden

Alles andere (Kanban, Prompt-Generator, MCP, Grok Build, Tollgate, Dashboard) kommt **bewusst später**.

## 3. Architektur-Prinzipien

- Core bleibt stabil und „dumm“
- Klare Modultrennung (`core / storage / ui / services / api`)
- Kommunikation über interne API + Events
- Storage und UI austauschbar
- Neue Features = neues Modul unter `services/`

## 4. Phasen

| Phase | Inhalt | Ziel |
|---|---|---|
| 1 | Core + Storage + Events | Stabiles Fundament |
| 2 | Einfache UI + Thread-Switcher + Snapshot | Erste nutzbare Version |
| 3 | Polish, Fehlerbehandlung, erste echte Nutzung | Alltags-tauglich |
| 4a | Prompt-Generator (lokal, kein Execute) | fertig |
| 4b | MCP stdio + Handoff | fertig |
| 4c | Grok-Build-Bridge (Paket, kein Start) | fertig |
| 4d | Tollgate-Wrap (lokales Gate) | fertig |
| 4e | Dashboard (nur Ansicht) | fertig |
| 5a | Gnom-Hub-Bridge (Paket, kein POST) | fertig |

## 5. Erfolgskriterium

Ein Nutzer kann 5–10 Threads anlegen, beliebig zwischen ihnen wechseln und ist jedes Mal in unter 2 Sekunden wieder genau im richtigen Kontext inkl. Snapshot.
