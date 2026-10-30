# Gemeinsamer Befehlsvertrag v1

Dieser Vertrag konkretisiert B03–B05 des bestehenden [Gesamtplans](../plans/THREADDESK-GRAPH-PAPIERKORB-BEDIENUNG-20261026.md). Er führt keine zweite Fachlogik ein. `services/commands` registriert bestehende Domainservices; UI, CLI und MCP delegieren dorthin. Neu geplante Workshop-Arbeiten sind auf Nutzeranweisung vollständig gestrichen. Historische Nutzerdaten werden dadurch nicht gelöscht.

## Entdecken und aufrufen

`td command --catalog --limit 10 --offset 0` beziehungsweise der paketierte Server mit `--command-catalog` liefert `threaddesk.command-catalog.v1`. `next_offset` bis `null` verfolgen. Der Katalog enthält pro Command das Eingabeschema, Wirkung, Scope, Backends, tatsächliche Transportbeschränkungen, erforderliche Revision und aktuelle Verfügbarkeit. Die Registryrevision bindet auch aktuelle Modulrechte und Schemas; Aktivierung, Widerruf und Deinstallation wirken ohne Neustart. Ein eingetragener Command ist noch kein End-to-End-Nachweis.

Ein Aufruf verwendet `td command --request-file request.json` beziehungsweise `ThreadDeskServer --command-file request.json`:

```json
{
  "version": 1,
  "workspace_id": "ws-WERT_AUS_DEM_AKTUELLEN_KATALOG",
  "command": "graph.query",
  "arguments": {"mode": "work", "limit": 100}
}
```

`workspace_id` ist eine opake Bindung an das ausgewählte lokale Profil. Nach Profilwechsel den Katalog neu lesen. Optionale `catalog_revision` verhindert Aufrufe gegen einen inzwischen geänderten Katalog. Unbekannte Envelopefelder, ungültige JSON-Werte, externe Schemaabfragen und übergroße Eingaben werden vor dem Handler abgewiesen. Maximal 1 MiB Request, 24 Verschachtelungsstufen; Domainlimits können enger sein.

Mutation: eine eindeutige `operation_id` und die laut Katalog erforderliche `expected_revision` mitsenden. Erstellung nutzt Revision 0. Native Domainverträge erhalten exakt dieselbe Operation und Revision, keine verdeckte zweite Kennung. Bei Libraryimport bleibt die ursprüngliche Manifestoperation unverändert; `library.resume` erhält eine neue Commandoperation und referenziert `import_operation_id`.

## Antworten, Konflikte und Wiederaufnahme

Erfolg: `threaddesk.command-result.v1` mit Workspace, Katalogrevision, Command, SHA256-Ergebnisdigest und `result`. CLI ergänzt `ok`; Exitcode 0 bedeutet Erfolg, Exitcode 2 einen strukturierten Fehler. HTTP `/api/commands` verwendet dieselben Eingaben, Konflikte ergeben 409. MCP bietet neben `command_catalog`, `command_query` (ausschließlich Reads) und `command_invoke` automatisch ein konkretes Einzelwerkzeug für jeden verfügbaren registrierten Fachbefehl; alte Toolnamen bleiben erhalten. Schemas, Live-Discovery, Berechtigungen und Änderungsmeldungen beschreibt der [dynamische MCP-Vertrag](mcp-dynamic-v1.md).

CLI-/MCP-Resultate werden auf 24.000 Bytes begrenzt. Große Ergebnisse erscheinen als JSON-Textseiten: `result_page`, `encoding=json-text-codepoint-pages`, `offset`, `next_offset`, `total`. Beim Weiterlesen ursprünglichen Request plus `result_digest` und `result_offset` verwenden; alle Seiten in Reihenfolge verbinden und erst danach als JSON parsen. Bei zeitabhängigen Reads außerdem das zurückgegebene `snapshot_at` weitergeben. Ein geändertes Ergebnis führt zu `result_changed`; nie Seiten verschiedener Versionen vermischen. Große Exporte/Backups sind SHA256-gebundene Artefakte mit geschütztem Download, kein unbeschränkter Terminaltext.

Gleiche Operation und identischer kanonischer Request liefern den dauerhaften Ergebnisbeleg, ohne Wirkung oder Erfolgsevent zu wiederholen. Andere Nutzlast unter derselben Operation ergibt `operation_conflict`. Veraltete Objektversion ergibt `revision_conflict`; den Entwurf behalten, aktuellen Stand lesen und bewusst entscheiden.

`command.operation` zeigt `pending`, `failed` oder `complete`. Vor Dateisystem-, Netzwerk- und OS-Effekten wird eine Reservation gespeichert. Unbestätigte Wirkung wird niemals blind wiederholt. `command.reconcile` übernimmt ausschließlich nachweisbare, exakt gebundene Ownerreceipts und führt die ursprüngliche Mutation nicht erneut aus. Unterstützte Owner: Threadmanagement, Knowledge, Libraryvorgänge einschließlich bestätigtem Öffnen, gespeicherte Graphansichten, Trash und Handoffausgabe. Fehlt ein prüfbarer Ownerbeleg, bleibt `owner_receipt_unverifiable` eine konkrete Grenze; ein äußerer Fehler beweist keine ausgebliebene Wirkung.

Eine ausdrücklich bestätigte endgültige Löschung darf im v2-Purgevertrag aufgeführte historische Resultatkopien in Tombstones reduzieren. Requesthash, Operationsidentität und Ausführungsstatus bleiben erhalten. Replay ist dann ausdrücklich `content_purged`, statt gelöschten Inhalt erneut auszugeben. Fremde offene Commandreservationen und mehrdeutige Inhaltskopien blockieren Purge. Details: [Papierkorbvertrag](trash-v1.md).

## Oberfläche und sichere Transportgrenzen

Öffentliche HTTP-Aufrufe bleiben an die bestehenden Localhost-/Origin-/CSRF-Regeln gebunden. Fähigkeiten des Graphclients sind kurzlebige, workspacegebundene Zustellungsrechte; sie sind kein Ersatz für Fachberechtigungen. `graph_view.apply` gilt erst nach tatsächlicher Anwendung und geprüftem UI-ACK als angewendet. `queued` und `waiting_for_client` sind keine Erfolgsmeldung für die sichtbare Ansicht. Der [Graphvertrag](graph-activity-v1.md) beschreibt Kontrolle und Änderungsstatus genauer.

Die optionale Ownerkontextsuche `search.*` ist ausschließlich `local`/`cli` zugänglich. HTTP/MCP/Rooms erhalten dafür keine versteckte Freigabe. Dateisuche im autorisierten Bibliotheksvertrag bleibt davon getrennt. Module verwenden den bestehenden [deklarativen Modulvertrag](module-commands-v1.md), keine Ausführung hochgeladenen Codes.

KiraBridge wird nicht verändert. Native KiraBridge-Verträge und der autorisierte sichtbare CLI-Weg sind verschiedene, offen benannte Zugänge. Für neue Writes ist der sichtbare Terminalweg verwendbar, wenn die aktuelle Bridge ihn tatsächlich autorisiert und ein freies sichtbares Terminal bestätigt. Tatsächlicher Principal, Taskreceipt, Abschluss und unabhängiger Readback gehören zum Nachweis. Ein lokaler Test oder MCP-Katalog beweist keine Bedienbarkeit aus ChatGPT. Unklare abgeschickte Aktionen zuerst anhand ihrer dauerhaften Operation abgleichen; nicht erneut absenden.

## Grenzen der Abnahme

Die skriptbaren privaten Fixtures `scripts/check_workspace_commands.py`, `scripts/check_workspace_operations.py` und `scripts/check_library_workflow.py` prüfen Originalerhalt und frische CLI-Prozesse; optional unterstützen sie den finalen Paketserver. Sie behaupten selbst keine Bridgeidentität. Netzwerkprüfungen verwenden echte originale Loopback-HTTP-Server, keine Modellanbieter. Produktionsdaten, fremde Originale und Code von KiraBridge werden nicht als Testfixture verwendet.

Der releasebezogene Beleg muss getrennt ausweisen: Quellimplementierung, gezielte Tests, tatsächliche Bridgeaufrufe, Pflicht-CI, integrierter Quellpin und installierter Paketpin. Kein Katalogeintrag und kein Teiltest setzt diese übrigen Spalten automatisch auf erfolgreich.
