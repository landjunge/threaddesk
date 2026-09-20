# Authority Event Envelope v1 (G0)

Stand: 2026-09-21. Verbindlich laut Notion *ThreadDesk — Authority Graph / Live Map*.

ThreadDesk **führt nichts aus**. Es speichert und zeigt Events. Kein sechster Produktdienst.

Schema: [`authority-event-v1.schema.json`](authority-event-v1.schema.json). Validator: `threaddesk.core.authority_event`.

## Verbotene Felder

Nicht im Event, auch nicht nested:

`secret`, `password`, `prompt`, `credential`, `api_key`, `token`, `access_token`, `raw_token`, `master_password`, `private_key`, `vault_payload`.

Werte, die wie Keys aussehen (`sk-…`, `Bearer …`), werden abgelehnt.

Statt Geheimnissen: `capability_id`, `result_ref`, `budget_ref`.

## Knoten (für G1, hier eingefroren)

Mensch, Agent/Worker, Workflow/Lauf, Aufgabe, Tool, Ressource, Projekt, Capability/Freigabe, Secret-Metadatensatz (kein Secret-Wert), Policy, Entscheidung, Ergebnis, Freeze/Incident.

## Kanten (für G1, hier eingefroren)

`delegated_to`, `invoked`, `requested`, `authorized_by`, `denied_by`, `used_capability`, `derived_from`, `created_under`, `read_from`, `wrote_to`, `cost_charged_to`, `frozen_by`, `belongs_to`, `result_of`, `supersedes`.

## Fünf Producer

| Tool | Darf erzeugen | Darf nicht |
|------|----------------|------------|
| **gnom-hub-v1** | `work.started`, `agent.invoked`, `delegation.created`, `tool.intent`, `tool.result`, `work.finished` | ThreadDesk-DB schreiben; TollGate/Authority umgehen |
| **agent-authority-lab** | `authority.requested/allowed/denied/freeze/unfreeze` | allgemeiner Orchestrator werden |
| **tollgate** | `budget.checked/charged`, `loop.detected`, `request.blocked`, `consumer.frozen` | Secrets lesen; Projektwissen besitzen |
| **4allpass** | `capability.granted/denied/revoked` (nur Metadaten) | Secret-Werte in Events |
| **threaddesk** | `graph.imported`, `incident.opened` | Arbeit starten; fremde DBs schreiben |

## Abnahme G0

Dasselbe Fixture kann ohne Produkt-UI von Hand in einen Graphen übersetzt werden. Tests in `tests/test_authority_event.py`.

G1 (Renderer) kommt danach. G2 (Gnom als Live-Producer) erst nach G1.
