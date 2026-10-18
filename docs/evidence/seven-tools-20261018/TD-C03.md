# TD-C03 – Wissensführung / knowledge and re-entry

Basis: main `bba99b03456ddf72a32c10d5d262f42cbcc30891` mit TD-C01/02.
Eigener Worktree `seven-tools-knowledge-design-20261018`; keine Nutzerinstallation,
Datenmigration, Agentenstarts oder Desktop-Auslieferung.

## Implementiert

- `knowledge_manage` mit bestehender Management-Quittung, Operationskennung,
  erwarteter Thread-/gegebenenfalls Knotenrevision und atomarem JSON-WAL-/SQLite-Weg.
- Bestehende KnowledgeNode/Relation/GraphEvent speichern Entscheidungen, verworfene
  Vorschläge, Aufgaben und offene Fragen. Fragen bleiben document/waiting mit
  typisierender Metadatenangabe; keine neue Datenbank oder Status-/Knotenliste.
- Ersetzen erhält früheren Beschluss und Quellen, markiert ihn superseded und
  verbindet einen neuen confirmed-Beschluss über follows/meaning=supersedes.
  Eine Antwort erhält die ursprüngliche Frage und eine gesonderte Auflösung.
- Gespeicherter Wiedereinstieg in Thread.extra; `get_reentry` liest nach Neustart
  höchstens 200 aktuelle/historische threadgebundene Knoten samt total/truncated.
- Quellen-/Revisionsangaben sind referenziert und unverified; Altangaben ohne
  Herkunft bleiben separat unknown. confirmed ist eine fachliche Entscheidung,
  kein technischer Nachweis, keine Rechteerteilung und kein Arbeitsstart.
- Sämtliche Wissensmutationen erhöhen die Threadrevision. Alte ausgestellte
  Handoffs werden dadurch veraltet; gespeicherte Pakete werden nicht verändert.

Exakte Actions, Shapes, Fehler und Grenzen: [MCP.md](../../MCP.md#td-c03-knowledge-and-re-entry--wissen-und-wiedereinstieg).

## Tatsächlich geprüft

- `tests/test_knowledge_memory.py`, `tests/test_knowledge_graph.py`,
  `tests/test_thread_management.py`: **69 bestanden** für den Kern einschließlich
  kompatibler Graph-/Managementwege.
- Nach Ergänzung der gezielten Absturz-/Quellen-Gegenfälle nur das veränderte
  `tests/test_knowledge_memory.py` erneut: **33 bestanden**. Kein Addieren der
  überlappenden Testzahlen zu einer erfundenen Gesamtzahl.
- JSON und SQLite: Neustart, gleiche/geänderte Operationskennung, alte Revision,
  fremde Threadzuordnung, keine Wirkung von Ausführungstext, Secret-/Zusatzfelder,
  atomarer Abbruch vor Quittung und bei mehrteiliger Ersetzung; JSON-WAL-Abbruch
  nach Commitplan stellt genau denselben Knoten und dieselbe Quittung wieder her.
- Der erste neue Prüflauf fand einen Testhelferfehler (fehlender action-Parameter),
  korrigiert und gezielt erneut geprüft. Kein Beleg einer Produktregression.
- Bestehende FastAPI/httpx-TestClient-Deprecation-Warnung bleibt sichtbar;
  kein Paketupgrade nur für diese Änderung.

Zusätzlicher real beobachteter JSON-Fehler: relativer Workspace plus zweite
Whiteboard-Schreibung scheiterte am Vergleich absoluter und relativer Pfade.
`cdd5017` normalisiert die Wurzel; innerhalb einer atomaren Graphänderung sind neu
staged Knoten nun referenzierbar. Zwei neue Regressionen plus bestehende Speicher-
und Whiteboardfälle: **33 bestanden**. Keine Datenverschiebung oder Migration.

## Abgrenzung / English

This is local source implementation and targeted isolated verification. It does
not prove live ChatGPT delivery, multi-user authorization or external source
verification. Imported/stored text never starts work. Existing workspace/operator
trust remains; permissions for other tools are not inferred from confirmed facts.
The root coordinator integrates/pins consumers separately.

At this core pin, old export construction reads legacy extra.decisions, not the
new graph knowledge. A bounded additive context.knowledge attachment for **newly
issued** handoffs is the next approved follow-up. Historical issued payloads,
hashes and receipts must remain byte-for-byte unchanged.
