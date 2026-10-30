# Deklarative Modulbefehle, Version 1

Ein vorhandenes `ModuleManifest` kann optional `commands` deklarieren. Alte Manifeste ohne dieses Feld bleiben gültig und veröffentlichen keine zusätzlichen Befehle. Installation aktiviert ein Modul nicht. Die vorhandene `ModuleRegistry` bleibt für Installation, Aktualisierung, Freigaben und Deaktivierung zuständig.

Es werden ausschließlich die unten genannten vorhandenen `ModuleContext`-Fähigkeiten angeboten. Ein Manifest kann keine Python-Datei, Importadresse, Shellaktion oder sonstigen ausführbaren Handler angeben.

```json
{
  "id": "project-notes",
  "name": "Project notes",
  "version": "1.0",
  "manifest_version": 1,
  "read_scopes": ["thread:read", "whiteboard:read"],
  "write_actions": ["whiteboard:append", "notes:write"],
  "approvals": ["notes:write"],
  "commands": [
    {"id": "thread", "capability": "read_thread"},
    {"id": "append", "capability": "append_whiteboard"},
    {"id": "records", "capability": "read_own_data"},
    {
      "id": "record",
      "capability": "write_own_record",
      "action": "notes:write",
      "required_approvals": ["notes:write"]
    }
  ]
}
```

Die vollständige Kennung ist beispielsweise `module.project-notes.thread`. Die relative Kennung verwendet Kleinbuchstaben, Zahlen und Bindestriche. `description` kann eine Beschreibung bis 500 Zeichen enthalten.

| Fähigkeit | Eingabe | Fachliche Berechtigung und Wirkung |
| --- | --- | --- |
| `read_nodes` | `kind`, optional `limit`/`offset` | Nur die passenden deklarierten `knowledge:<kind>`-Scopes beziehungsweise `knowledge:*`; liest Knotendaten |
| `read_thread` | `id` | `thread:read`; liefert ID, Revision, Titel, Status, Beschreibung und Notizen, keine Dateien oder Storeobjekte |
| `read_whiteboard` | `id`, optional `limit`/`offset` | `whiteboard:read`; liest unveränderte Einträge |
| `append_whiteboard` | `id`, `actor`, `actor_type`, `entry_type`, `content`, veröffentlichte optionale Referenzfelder | `whiteboard:append`; ergänzt einen Eintrag und erhöht nur bei einem neuen Eintrag die Threadrevision |
| `read_own_data` | optional `limit`/`offset` | Liest nur die eigenen Modulrecords und deren gemeinsame Revision |
| `write_own_record` | `record_id`, `value`, `expected_revision` | Die im Manifest deklarierte feste `action` muss in `write_actions` enthalten und vollständig freigegeben sein; schreibt ausschließlich das eigene Moduldatendokument |

Jede Schreiboperation verwendet zusätzlich den gemeinsamen Command-Umschlag mit `operation_id` und expliziter `workspace_id`. `append_whiteboard` benötigt die zuvor gelesene Threadrevision im Umschlag. `write_own_record` benötigt die von `read_own_data` gelieferte Modulrevision. Die aktuellen vollständigen Schemas stehen im paginierten Commandkatalog.

`required_approvals` einer Deklaration müssen im Manifest enthalten und tatsächlich gewährt sein. Vor Aufruf werden die aktuelle Deklaration, Freigaben, Scopes und Aktivierung erneut geprüft. Ein gecachter alter Handler meldet bei geänderter Deklaration `catalog_conflict`. Deaktivierung beziehungsweise Rechteentzug sperren weitere Aufrufe. Bereits laufende Aufrufe werden dadurch nicht automatisch abgebrochen.

Der Katalog enthält den Modulvertrag mit Capability, Modulversion, Scopes, Aktionen, erforderlichen und gewährten Freigaben. Änderungen dieser Daten, der Schemata oder der Verfügbarkeit verändern seine deterministische Revision. Neu hinzugefügte Fähigkeiten oder geänderte Commanddeklarationen deaktivieren ein bestehendes Modul bis zu einer ausdrücklichen erneuten Aktivierung.

Große Permissionlisten werden im einzelnen Katalogeintrag ausdrücklich gekürzt und mit Gesamtzahlen sowie Digest über die vollständigen Werte versehen. Der veröffentlichte Verweis `modules.list` liefert die vollständigen Manifeste über die reguläre begrenzte Ergebnisausgabe. Ausführungsprüfungen verwenden immer die vollständigen aktuellen Rechte. Modul-ID und Modulversion sind auf 128 Zeichen begrenzt.

Eine optionale `input_schema` schränkt das veröffentlichte Capabilityschema zusätzlich ein. Sie kann es nicht erweitern. Externe Schemaadressen, ausführbare Handler, reguläre Ausdrücke und unbekannte Schlüssel sind gesperrt. Es gelten höchstens 64 Befehle pro Modul, 8 KiB pro Einschränkungsschema, acht Schemaebenen und 200 Schemaknoten. Request- und Antwortbudgets des Commandvertrags bleiben zusätzlich wirksam.

Eigene Modulrecords bleiben im vorhandenen `module-<id>-data.json`. Alle bestehenden `ModuleContext.write_own_record`-Writer teilen den Dateilock und erhöhen die additive gemeinsame `revision`. Das Dokument ist auf 10.000 Records und 16 MiB begrenzt. Deinstallation erhält die Daten.

Auf SQLite ist ein JSON-Artefakt keine SQL-Transaktion. Deshalb speichert der Dispatcher vor `write_own_record` eine dauerhafte Ausführungsreservierung; der Modulwriter prüft seine Revision unter eigenem Lock. Eine unklare Antwort ist über `command.operation` und unabhängiges `read_own_data` abzugleichen. Unbestätigte Operationen werden nicht blind wiederholt. Erfolgreich belegte identische Operationen liefern den vorhandenen Beleg.

Die alten dauerhaften Löschpfade von `ThreadService.delete`, `thread_manage(delete)` und der CLI bleiben als gesperrter Kompatibilitätsvertrag erhalten. Sie liefern `legacy_delete_requires_purge_contract`; auch `--legacy-permanent` umgeht diese Grenze nicht. Wiederherstellbares Entfernen verwendet `trash.move`, endgültiges Löschen ausschließlich den expliziten Vorschau-/Bestätigungsvertrag von `trash.purge`.

Die deklarativen Befehle nutzen denselben HTTP-/MCP-/CLI-Dispatcher wie die eingebauten Funktionen. Das erweitert keine nativen KiraBridge-Schreibverträge. Tatsächliche Bedienbarkeit aus ChatGPT benötigt weiterhin den konkret autorisierten und geprüften vorhandenen Transport, einschließlich Readback.
