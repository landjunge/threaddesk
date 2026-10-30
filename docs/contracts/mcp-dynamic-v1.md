# Dynamische MCP-Fachwerkzeuge v1

Die vorhandene `CommandRegistry` ist die einzige Quelle der fachlichen
Werkzeugdefinitionen. `McpCommands` projiziert sie auf MCP und ruft die bestehende
`CommandApplication` auf. Kein Reflection-Export beliebiger Pythonmethoden,
zusätzlicher Dispatcher, Datenspeicher oder KiraBridge-Code wird eingeführt.
Neue registrierte Quellbefehle werden beim nächsten Discovery automatisch
berücksichtigt; neue Modulbefehle verwenden den bestehenden deklarativen
[Modulvertrag](module-commands-v1.md).

## Namen und Discovery

Einzelwerkzeuge beginnen mit `td_`. In der Command-ID werden `.` durch `__` und
`_` durch `_u` ersetzt; ASCII-Buchstaben, Zahlen und Bindestriche bleiben erhalten.
Andere Zeichen werden hexadezimal maskiert. Überlange Namen werden auf ein
lesbares Präfix und 40 SHA256-Hexzeichen gekürzt. Alle Namen erfüllen den
bestehenden KiraBridge-Namenvertrag `[A-Za-z][A-Za-z0-9_-]{0,63}`; insbesondere
bleiben `a.b` und `a_b` verschieden. Ein tatsächlicher Namenskonflikt wird
abgewiesen. Die vollständige Command-ID steht in `_meta.threaddesk.id`.

`tools/list` ist eine aktuelle, deterministisch geordnete Projektion. Es liefert
Einzelwerkzeuge ausschließlich für `availability=available` im MCP-Transport.
Scope, aktives Speicherbackend, Modulaktivierung, deklarierte Fähigkeiten und
tatsächlich gewährte Modulfreigaben werden berücksichtigt. Die bestehenden
Legacywerkzeuge und drei Commandgateways bleiben kompatibel. Ein durch den
vertrauenswürdigen Serverkontext eingeschränkter `McpBridge(allowed_scopes=...)`
filtert auch Legacywerkzeuge und verhindert deren direkten Aufruf als Umgehung.
Ohne solche Einschränkung gilt der bestehende lokale Operator-/Workspacekontext;
dadurch wird keine zusätzliche Principalidentität behauptet.

Der stdio-Server kündigt `tools.listChanged=true` an. Nach
`notifications/initialized` prüft sein Hauptthread die Katalogrevision bei
Requests und etwa einmal pro Sekunde bei ruhender Eingabe. Änderungen durch
einen anderen ThreadDesk-Prozess führen zu `notifications/tools/list_changed`.
Ein begrenzter Eingabethread liest nur stdin; SQLite wird ausschließlich im
Hauptthread benutzt. Jede `tools/list`-Anfrage prüft erneut. Eine nicht lesbare
Discovery führt zum protokollierten Requestfehler statt zu einer behaupteten
aktuellen Werkzeugliste. Ein Client muss die Liste nach einer Änderungsmeldung
neu lesen; ThreadDesk kann dessen Cacheverhalten nicht erzwingen.

Die Transportmechanismen folgen den offiziellen MCP-Verträgen für
[Werkzeuge und Änderungsmeldungen](https://modelcontextprotocol.io/specification/2025-11-25/server/tools).
Die vorhandene Protokollversion des stdio-Handshakes bleibt kompatibel.

## Konkretes Eingabeschema und Rechte

Jedes Einzelwerkzeug veröffentlicht:

- `workspace_id`: Pflichtbindung an den aktuell ausgewählten Workspace.
- `arguments`: das konkrete, quellverantwortete JSON-Schema des Fachbefehls.
- `operation_id`: Pflicht für jede Mutation.
- `expected_revision`: Pflicht gemäß Revisionsziel beziehungsweise nativem Vertrag.
- Optionale `catalog_revision`, `result_offset`, `result_digest`, `snapshot_at`
  aus dem gemeinsamen [Commandvertrag](commands-v1.md).

Bei nativen Verträgen injiziert `CommandApplication` Operation und Revision aus
dem Envelope vor der Fachvalidierung. Diese beiden Pflichtfelder werden deshalb
im veröffentlichten Fachschema nur aus dessen oberster `required`-Liste entfernt
und ins äußere Schema übernommen. Optionale Kopien im Fachobjekt bleiben erlaubt;
abweichende Werte werden durch die bestehende Anwendung abgewiesen. Die übrigen
Fachbedingungen bleiben bestehen, auch bedingte Regeln und Modulschemaeinschränkungen.

`_meta.threaddesk` enthält den vollständigen öffentlichen Commandvertrag,
insbesondere unverändertes Quellschema, Command-ID, Scope, Wirkung,
Revisionsziel, erforderliche Operation, Backend-/Transportgrenzen,
`workspace_id` und gegebenenfalls den Modulberechtigungsvertrag. Metadaten und
MCP-Annotations sind Beschreibungen; sie erteilen keine Berechtigung.

Beim Aufruf werden Workspace, aktuelle Verfügbarkeit, Schema, Operation,
Revision und optionale Katalogbindung durch dieselbe `CommandApplication`
geprüft. Ein bekannter Werkzeugname bleibt nach Deaktivierung oder Rechteentzug
gesperrt. Requestfelder können weder Scopes noch Transport, Principal,
Workspaceprozess, Programmdatei oder Modulfreigaben auswählen. `search.*` und
`server_sync.owner_reference` behalten ihre Owner-/CLI-Grenze.

## Belege, Konflikte und Löschschutz

Ergebnisse verwenden `threaddesk.command-result.v1` mit Workspace,
Katalogrevision, fachlichem Resultat und `result_digest`. Mutationen liefern
zusätzlich ihre Operationsidentität und `duplicate`. Der stdio-Transport gibt
Objektergebnisse als `structuredContent` sowie denselben JSON-Inhalt als
Textblock zurück. Fehler behalten die vorhandenen Codes und `isError=true`.

Identische Wiederholung verwendet den dauerhaften Commandbeleg. Geänderte
Nutzlast unter derselben Operation führt zu `operation_conflict`, veraltete
Version zu `revision_conflict`. Nach unklarer Zustellung liest der Client
`command.operation`; OS-/Netzwerkeffekte werden nicht blind wiederholt.
Große Resultate verwenden die bestehenden digestgebundenen Readbackseiten.
Ein dynamischer Lesebefehl löst keinen zusätzlichen Indexrefresh aus.

Der Adapter schwächt keine Fachbestätigung: Papierkorb-Ampel,
objekt-/generations-/digestgebundene Löschvorschau und ausdrückliche
Bestätigung für endgültiges Löschen bleiben bei den bestehenden Services.
Das Veröffentlichen von `trash.purge` erteilt selbst keinen Löschauftrag.

## Nachweisgrenze

`tests/test_mcp_dynamic_commands.py` prüft JSON und SQLite, vollständige
autorisierte Registryabdeckung, Namensgrenzen, künftige Registrierung im
gleichen Bridgeobjekt, Fachschemas, Scope-/Backend-/Ownergrenzen,
Native-Operationen, Wiederholung, Konflikte, Readback sowie Modulinstallation,
Aktivierung, Schemaänderung, Rechteentzug und Deinstallation. Ein separater
echter stdio-Prozess belegt Discovery, Fachaufruf und eine Änderungsmeldung bei
ruhender Eingabe nach externer Modulaktivierung.

Diese Prüfungen belegen den ThreadDesk-Endpunkt. Sie beweisen weder, dass eine
vorhandene KiraBridge-Konfiguration auf diesen Quellstand zeigt, noch eine
bestimmte KiraBridge-Principalberechtigung. Eine konkrete Gegenstellenprüfung,
finaler Quellpin, Pflicht-CI und installierter Paketpin müssen im
auftragsbezogenen Ergebnisbeleg gesondert dokumentiert werden.
