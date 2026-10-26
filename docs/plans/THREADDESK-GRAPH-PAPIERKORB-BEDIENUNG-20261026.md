# Konkreter ThreadDesk Plan für Bedienung, Papierkorb und Graph

Stand: 26. Oktober 2026. Produktbasis `07e10bf`; die anschließenden Commits dieses Auftrags ändern ausschließlich Planung, Projektregeln und Nachweise. **Fortgeschriebener Auftrag: Bibliotheksimport, verbindliche Indexsuche und Dateimanager jetzt schrittweise umsetzen.** Dieser Plan ersetzt die Umsetzungszuweisungen des [vorherigen Plans](THREADDESK-KIRABRIDGE-PLAN-20261026.md). Dessen Fehlerdiagnose bleibt gültig.

ThreadDesk wird vollständig bedienbar, erhält einen wiederherstellbaren Papierkorb und anschließend eine deutlich bessere Graphansicht mit nachvollziehbarer Dateiaktivität. ChatGPT muss alle Fachaktionen über vorhandene KiraBridge-Zugänge ausführen können. In diesem Auftrag wird ausschließlich ThreadDesk geplant und gebaut; KiraBridge bleibt eine externe Gegenstelle. Es gibt keine KiraBridge-Baupakete.

## 1. Verbindliche Reihenfolge und Abschluss

1. Bestehende Konsistenzfehler beheben und einen gemeinsamen fachlichen Befehlsvertrag für UI, CLI und MCP herstellen.
2. Vollständige Bedienbarkeit inventarisieren und für jede Funktion den tatsächlich verfügbaren KiraBridge-Aufrufweg belegen.
3. Papierkorb mit Wiederherstellung, Referenzerhalt, Backup und Syncschutz implementieren.
4. Dateiaktivität sauber erfassen und daraus eine versionierte Graphabfrage ableiten.
5. Neue Graphtechnik im echten Desktop vergleichen, anschließend Übersicht, Zeitmodus und vollständige Bedienung bauen.
6. Review, Pflicht-CI, Commit/Push/Merge, Paket und installierte Desktop-Version aus demselben Laufzeitstand abnehmen.

Der anschließende Nutzerauftrag erteilt die Umsetzungsfreigabe für Bibliotheksimport, Indexsuche, Graph-Dateimanager, zugehörigen Dateipapierkorb und sofortige KiraBridge-Bedienung. Die genaue aktuelle Reihenfolge und Abnahme stehen in Abschnitt 11. Nicht hierzu gehörende spätere Themen bleiben zurückgestellt. Kein Diagramm, Katalog oder Dokumentationsmerge wird als fertig implementierte Funktion ausgegeben.

## 2. Zusammenfassung vorhandener Brainstormings

Die maßgebliche [Brainstorming- und Übergabeseite vom 22.10.2026](https://app.notion.com/p/401c08fa272a81f9a159e8bee3465115?pvs=204), gespeicherte ThreadDesk-Ideen und lokale Anforderungsdateien wurden tatsächlich gelesen. Der [Quellen- und Anforderungsabgleich](BRAINSTORMING-SYNTHESE-20261026.md) hält Herkunft, Beschlussstatus und noch fehlende Originale fest.

| Thema | Konsolidierte Anforderung | Behandlung im konkreten Plan |
| --- | --- | --- |
| Zeitfarben | Echte Dateiänderungen und tatsächlich veranlasste Dateizugriffe sichtbar machen; Lesen und Ändern getrennt. Graphöffnung und technische Verarbeitung zählen nicht. | Zwei getrennte Zeitfelder und klar benannte Farbmodi; Aktivitätsquelle im Inspektor erklären |
| Übersicht und lebendiger Graph | Gute Orientierung, frische Daten, sinnvolle Cluster und stabile Positionen | Abfrage-/Layout-/Darstellungsmodule trennen, gezielte Aktualisierung, kein ständiges Springen |
| Papierkorb | Threads einschließlich Graphbeziehungen wiederherstellen; endgültige Löschung gesondert | Eigener Lebenszyklus mit stabilen IDs und Generationen, kein bloßes Archiv |
| ChatGPT-/Sprachbedienung | Threads und Whiteboards lesen, organisieren und bearbeiten; neuer Auftrag erweitert dies auf alle Fachaktionen | Gemeinsame Befehle und vollständige End-to-End-Matrix über vorhandene KiraBridge |
| Anhänge und Beziehungen | Dateien auf Knoten als Anhänge, unklare Ziele in zentrale unzugeordnete Aufnahme; Beziehungen aus bestätigter Struktur ableiten | Vorhandene Bibliotheks-/Empfangsmodule weiterverwenden; normale Dateiquellen nicht ungefragt löschen |
| Gedächtnis | Offene Fragen, Arbeitschronik, Wiederaufnahme, Quellenfilter, Vorschläge für Verknüpfungen | Aktivitätsgrundlage jetzt; semantische Suche/automatisches Gedächtnis als spätere, getrennte Vorschlagsmodule |
| Originalerhalt | Ideen konsolidieren, Quellen und Beziehungen behalten, Dubletten erst prüfen | Abgeleitete Zusammenfassung statt Zusammenkopieren privater Originaltexte; keine vorsorgliche Bereinigung |
| Desktop und Hilfe | Gut lesbare feste Desktopbereiche, bestehende Tastaturbedienung und beschlossenen H-Hilfevertrag erhalten | Graphänderung erhält bestehende Bedienverträge, DE/EN und scrollbare kleine Fenster |

Die Dateien TD-IDEA-002 bis TD-IDEA-019 sind teilweise nur inventarisiert. Fehlende Originalbytes werden nicht durch Dateinamen ersetzt. Insbesondere „Graph-Animation“ und „Lebendiger Graph“ enthalten als bloße Titel noch keine Festlegung auf 3D, Daueranimation oder einen bestimmten Renderer.

Offener früherer Konflikt: Eine Quelle wünscht automatische Beziehungen, eine andere verlangt Vorschläge statt stiller Änderungen. **Konkrete Planungsempfehlung:** deterministische Beziehungen aus bestätigten Zuordnungen automatisch pflegen; semantische Ähnlichkeit als bestätigungspflichtigen Vorschlag führen. Die Herkunft beider Aussagen bleibt sichtbar.

## 3. Iststand und zuerst zu behebende Fehler

Die vorige Teamdiagnose hat zwei Fehler auf JSON und SQLite reproduziert: Veraltete UI-Notizen überschreiben neuere Inhalte ohne Revisionskonflikt; eine zurückgerollte Threaderstellung sendet bereits `thread.created` und `thread.switched`. [Belege und Reproduktionen](../evidence/threaddesk-kirabridge-audit-20261026/README.md).

Paket B01 bindet alle UI-/CLI-Mutationen an die angezeigte Objektversion und eine stabile Operationskennung. Konflikte ergeben maschinenlesbare Fehler/HTTP 409, erhalten den Entwurf und überschreiben nicht automatisch. Paket B02 sammelt Ereignisse innerhalb der vorhandenen Fachtransaktion und veröffentlicht sie erst nach Commit; Rollback und identischer Replay dürfen keine Erfolgsevents erzeugen.

Heute gibt es 34 MCP-Tools und 12 explizit lesend freigegebene Tools. Whiteboard und weitere Fachaktionen fehlen im Katalog. Der live abgefragte dynamische KiraBridge-Katalog war deaktiviert (`enabled=false`); das ist kein Beleg einer fehlerhaften Verbindung. Die alte Karte führt 420 Layoutiterationen mit paarweisem Abstoßungsloop synchron aus und erzeugt SVG-Elemente pro Knoten. Eine konkrete bisherige Leistungsgrenze wurde nicht gemessen.

## 4. Vollständig bedienbar durch ChatGPT

### Gemeinsame Commands innerhalb ThreadDesk

`services/commands/` enthält kleine Module für Modell, Registry, Dispatcher, Fehler und Domänenspezifikationen. `CommandSpec` besitzt stabile ID, Modul, Version, Aliasnamen, Input-/Output-Schema, Handler, Wirkung, Scope, Workspace-/Objektbindung, Backendunterstützung und Anforderungen an Revision/Operationskennung. UI, CLI und MCP delegieren an dieselbe Fachlogik. Die vorhandene `ModuleRegistry` bleibt für Installation, Aktivierung und Freigaben zuständig; keine zweite Modulsteuerung bauen.

Domänen: Threads/Kontext, Snapshots/Wiedereinstieg, Whiteboard, Akteure/Module, Wissen/Graph, Suche, Bibliothek/Dateien, Handoffs/Returns, Papierkorb, Datenprofile/Backup/Migration, Räume/Server-Sync, Hausmeister/Einstellungen, Vorschauen/Exporte und Graphansichten. Jede öffentliche UI-Fachaktion besitzt genau einen Matrixeintrag. Reine Darstellung wie Browserzoom benötigt keinen erfundenen Fachbefehl; Graphkamera, Auswahl und gespeicherte Ansicht bekommen steuerbare Ansichtsoperationen.

### Heute verfügbare Transportwege korrekt einplanen

Der dynamische KiraBridge-Proxy unterstützt geprüfte Reads. Sein statischer ThreadDesk-Schreibvertrag erlaubt genau zehn vorhandene Verwaltungsaktionen; neue native Writes wie `trash.restore` oder `graph_view.save` passen nicht automatisch hinein. Auch am gelesenen RC17-Quellpin `14468ad` ist diese Grenze vorhanden. Eine ThreadDesk-Registry allein beseitigt sie nicht.

ThreadDesk baut deshalb eine vollständige öffentliche CLI mit strukturiertem JSON-Eingang/-Ausgang, stabilen Exitcodes, begrenzten Seiten, Workspaceidentität, Revisionsprüfung, Idempotenz und Operationsstatus. ChatGPT kann sie über die **bereits vorhandene KiraBridge-Terminalsteuerung** eines ausdrücklich zugewiesenen sichtbaren und freien Terminals bedienen. Dies ist ein offen ausgewiesener Transportmodus, kein unsichtbarer Ersatzpfad. Keine Eingabe in beschäftigte/unbestätigte Fenster, kein direkter Datenbankzugriff, keine als Read getarnte Mutation und keine Befehle in Notiztexten.

Der native MCP-/Bridgeweg und der sichtbare CLI-Modus stehen getrennt in der Abnahmematrix. Ohne verfügbaren autorisierten Transport bleibt eine Aktion als blockiert ausgewiesen. Wird ausschließlich native dynamische Schreibbedienung ohne Terminal vorausgesetzt, ist das eine externe Bridge-Vertragsabhängigkeit; dieser Auftrag verändert KiraBridge dafür nicht und behauptet trotzdem keine vollständige Abnahme.

### Abnahme jeder Funktion

Matrixspalten: Command-ID, UI-Aktion, Wirkung, Input-/Output-Version, Scope, Backend, nativer MCP-/Bridgezugang, sichtbarer CLI-Zugang, Erfolg, Konflikt, Replay, unabhängiger Readback und konkreter Prüfbeleg. Vollständig bedeutet **jede** Fachaktion hat einen tatsächlich ausgeführten zulässigen Aufrufweg. Registrierung oder eine erfolgreiche Teilmenge genügen nicht.

Mutationen erhalten `operation_id` und erwartete Objekt-/Lebenszyklusrevision; atomarer Ergebnisbeleg und Statusabfrage erlauben Abgleich nach Verbindungsabbruch. Ein unklarer Zustand bleibt `unknown`; kein blindes Replay. Öffentliche und interne Operationskennungen nicht vermischen. Große Ergebnisse über Pagination beziehungsweise klar begrenzte Artefakte liefern, keine unbeschränkten Terminalausgaben.

## 5. Papierkorb als eigener Lebenszyklus

### Verhalten und Datenvertrag

„Archiviert“ bleibt ein Arbeitsstatus. „Im Papierkorb“ ist eine davon getrennte Lebenszykluseigenschaft. Normal sichtbare Listen, Suche, Graph und normale Exporte blenden betroffene Objekte aus; direkte Mutation meldet `object_in_trash`. Die Papierkorbansicht erklärt Titel, Objektart, Löschzeit, Herkunft und mögliche Wiederherstellungshindernisse.

`TrashEntry` enthält `trash_id`, Objekt-/Workspace-ID, Generation, Trashrevision, Objektversion beim Verschieben, Löschzeit, belegte Akteurzuordnung, ursprünglichen Status, Organisations-/Referenzinformationen, Referenzdigest sowie Operationsbelege. Inhalt und Geschichte behalten ihre ursprünglichen IDs. Löschen → Wiederherstellen → erneut Löschen ergibt eine neue Generation; eine alte Restoreanfrage darf die neue Löschung nicht aufheben.

| Command | Wirkung und Abschluss |
| --- | --- |
| `trash.list/get/preview` | Reine Reads mit Cursor und Referenzübersicht; keine Lebenszyklusänderung |
| `trash.move` | Exakte Auswahl/Revision und bei Sammelaktion Previewdigest; atomare Markierung, aktive Auswahl bereinigen |
| `trash.restore` | Exakte Trash-ID/Generation/Revision; gleiche Thread-, Snapshot-, Whiteboard- und Graph-IDs wieder sichtbar |
| `trash.purge_preview` | Konkrete dauerhaft betroffene Daten, erhaltene Referenzen und Blocker anzeigen |
| `trash.purge` | Ausdrücklicher endgültiger Löschauftrag für genau diese Auswahl, Revision und Digest; minimalen Tombstone/Operationsbeleg behalten |

**Vorgeschlagener Anfangsstandard:** keine automatische Fristlöschung. Retention wäre eine spätere sichtbare Einstellung. Purge ist keine Zusage kryptografischer Vernichtung alter Backups. Dateien außerhalb der ThreadDesk-eigenen Ablage bleiben unberührt.

### Beziehungen und Eigentum

Threads samt eigener Notizen, Snapshots und Whiteboardgeschichte zuerst unterstützen. Wissensknoten und Kanten folgen im selben Fachvertrag: Kanten bleiben gespeichert, im Normalgraph unsichtbar, wenn ein Endpunkt im Papierkorb liegt. Beziehungen zu weiterhin aktiven Objekten nicht blind löschen. Unterthreads und Nachbarprojekte gehören nicht automatisch einer Löschkaskade.

Restore erhält IDs, Provenienz und Beziehungen. Ein inzwischen fehlender oder ebenfalls gelöschter Elternknoten wird als ungelöste Referenz angezeigt; kein neuer Ersatzinhalt oder fremdes Elternprojekt wird erfunden. Wiederherstellung macht den Thread nicht ungefragt zur aktiven Auswahl.

Libraryrecords, geteilte Blobs und externe Originaldateien sind getrennte Eigentumseinheiten. Purge darf eine gespeicherte Kopie nur ohne verbleibende aktive oder wiederherstellbare Mitreferenzen entfernen. Offene/unklare Handoffs und Transfers können Purge blockieren; der Papierkorb beendet keine Prozesse, löst keine Ausführungsreservierung und sendet nichts erneut. Einzelne Whiteboardeinträge/Auditbelege werden nicht durch eine generische Löschfunktion umgeschrieben.

### Backend, Backup, Migration und Sync

`services/trash.py` enthält den Fachservice, `storage/protocols.py` ein kleines `TrashStore`-Protokoll. SQLite erhält eine versionierte Migration; JSON bindet Lebenszyklusdaten in die vorhandene Transaktions-/Journalgrenze ein. Alte physische Löschfunktionen bleiben nur im kontrollierten Purgepfad. Die heutige dokumentierte dauerhafte `delete`-Semantik braucht einen expliziten versionierten Übergang mit aktualisierten Clients, keine stille Umdeutung.

Alle konfigurierten schreibenden Clients benötigen kompatible Pins. Eine neue JSON-Sperrdatei schützt nicht gegen beliebige alte Programme, die sie nie beachten; diese Writer müssen vor Aktivierung tatsächlich getrennt oder aktualisiert werden.

Backup-/Portable-/Library-Manifeste und Migrationslisten nehmen Papierkorb, Generationen und Tombstones ausdrücklich auf. Die heutige SQLite-Artefaktallowlist sichert ein beliebiges neues `trash/`-Verzeichnis nicht automatisch vollständig. Backuprestore muss Papierkorbinhalte als solche erhalten.

Raum-Sync darf einen gelöschten Thread beim Eintreffen alter Whiteboarddaten nicht als Hülle neu anlegen. Server-Metadatensync behandelt Abwesenheit heute ausdrücklich nicht als Löschung: versionierte Tombstones und Restoregenerationen ergänzen, alte Gegenstellen eindeutig behandeln. Delete/Edit/Restore-Konflikte bleiben erhalten; Zeitstempel allein entscheiden sie nicht. Beide Seiten gehören zum bestehenden ThreadDesk-Syncmodul, nicht zu KiraBridge.

## 6. Graphansicht und aktuelle Technikwahl

### Empfehlung nach Primärquellenrecherche

**Zielkandidat ist Sigma.js 4 mit Graphology und ForceAtlas2 im Webworker.** Die aktuelle [Sigma-Einführung](https://www.sigmajs.org/get-started/quickstart/) dokumentiert v4.0.3 und Graphology 0.26.0. [ForceAtlas2](https://graphology.github.io/standard-library/layout-forceatlas2.html) bietet Worker-Lifecycle und eine explizite Barnes-Hut-Option für die Abstoßungsberechnung. Bei Umsetzung nach dem Vergleich exakt pinnen und lokal bündeln; keine Laufzeit-CDNs.

| Technik | Eignung und Planentscheidung |
| --- | --- |
| Sigma 4 / Graphology | WebGL2, getrennte Graphdaten/Layout/Renderer; erster Kandidat für erkundbare Übersicht, MIT-Lizenztexte mitliefern |
| ForceAtlas2 im Worker | Layout aus dem UI-Thread entfernen, Barnes-Hut ausdrücklich konfigurieren, stabile Start-/Fixpositionen und stop/kill einsetzen |
| Cytoscape.js | Funktionsreiche Alternative für stärkere direkte/zusammengesetzte Graphbearbeitung; im begrenzten Vergleich berücksichtigen, keinen zweiten großen Renderer dauerhaft pflegen |
| WebGPU | Aktuelle WebKit-Unterstützung ist real; konkrete Tauri/WKWebView-/GPU-Verfügbarkeit trotzdem messen. Kein verpflichtender Unterbau des ersten Ausbaus |
| Cosmos/Cosmograph | Paket-/Lizenzbedingungen nicht pauschal MIT nennen; ohne konkrete Freigabe keine Standardabhängigkeit |

[Cytoscape-Dokumentation](https://js.cytoscape.org/), [WebKit Safari 26](https://webkit.org/blog/17333/webkit-features-in-safari-26-0/), [Anbieter-Lizenzbedingungen Cosmograph](https://cosmograph.app/licensing/). Der [Recherchebeleg](../research/GRAPH-TECHNIK-20261026.md) hält Vergleich, Quellen und ungeprüfte Punkte fest; sein ursprünglicher Aktivitätsvorschlag wird durch den quellenbasierten Vertrag in Abschnitt 7 präzisiert.

### Konkrete Oberfläche

Oben Suche sowie Projekt-, Typ-, Status- und Zeitfilter; mittig eine ruhige zweidimensionale Karte; seitlich ein vollständiger Inspektor; unten Zeit-/Farblegende und Daten-/Verbindungsstand. Auswahl, Bearbeiten, Beziehungen, Anhänge, Papierkorb und Wiederherstellung sind aus Inspektor und gleichwertiger Liste erreichbar.

Suche springt zum Treffer, fokussiert Nachbarschaft mit ein/zwei Schritten und erklärt Beziehungsarten. Projektcluster beruhen zunächst auf bestätigten Zuordnungen. Rechnerische Communities sind optional gekennzeichnet und erzeugen keine neuen Fachrelationen. Labels erscheinen nach Bedeutung und Zoomstufe; ausgewählter/fokussierter Knoten bleibt beschriftet.

Positionen, fixierte Knoten, Filter und Kamera in versionierten Ansichten speichern. Filteränderung startet keine komplette Simulation. Reale Änderungen gezielt nachladen, während Auswahl/Entwurf erhalten bleiben. Ein unterbrochener Datenkanal zeigt ausdrücklich seinen Zustand; keine vorgetäuschte Echtzeit.

Statusfarbe und Zeitfarbe sind benannte getrennte Modi. Im Zeitmodus bleiben Typform, Statussymbol, Auswahl, Hover und Warnung deutlich. Bewegung abschaltbar und Reduced Motion respektiert; keine dauernde dekorative Simulation. Bestehende Tastatur-, Link- und DE/EN-Bedienung sowie den beschlossenen H-Hilfevertrag erhalten; dessen aktueller Implementierungsstand wird gesondert geprüft.

Canvas-/GPU-Knoten sind keine barrierefreien DOM-Steuerelemente. Deshalb vollständige Tastatur-/Screenreader-Listenansicht mit DOM-Inspektor und sichtbarem Fokus, keine tausend unsichtbaren Tabstopps. GPUausfall oder Kontextverlust lässt die Fachbedienung in dieser Ansicht verfügbar. [WAI Nichttextkontrast](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast) beschreibt mindestens 3:1 für relevante Zustands-/Grafikindikatoren unter den genannten Ausnahmen; Texte und Farben getrennt prüfen.

### Messgate vor endgültiger Rendererentscheidung

Gleiche synthetische Fixtures mit 100/1.000/10.000 Knoten, sparsamen Beziehungen, zusätzlich dichter Stressfall, lange Labels, isolierte Komponenten und Sternstruktur. Aktuelle SVG-Baseline, Sigma-Kandidat und bei Bedarf Cytoscape vergleichen. Tatsächliche installierte Tauri/WKWebView-Achse, Chromium und GPUausfall prüfen; Hardware, Pixelratio, Labels, Kanten, Initialisierung, Speicher, Layoutdauer, Paketgröße und Lizenzen protokollieren.

Vorgeschlagene Ziele für 1.000 Knoten auf dem dokumentierten Ziel-Mac: erste bedienbare Sicht ≤2 Sekunden, p95 Pan-/Zoomframe ≤33 Millisekunden, Auswahlfeedback ≤100 Millisekunden. Für 10.000 Knoten Level-of-Detail und Teilgraph statt eingefrorener Oberfläche. Diese Ziele sind noch ungemessen; nach dem Spike verbindlich festlegen. Kein Leistungsversprechen aus Bibliotheksmarketing.

## 7. Zeitfarben mit richtiger Bedeutung

### Relevante Ereignisse

Die Originalquelle fordert Dateiänderung **und** echten Zugriff, getrennt erkennbar. Deshalb `file_modified_at` und `file_accessed_at` mit Herkunft führen. Statuswechsel, Graphöffnung, Layout, Indexierung, Sync-Empfang, Cache, Backup oder Restore setzen sie nicht auf jetzt. Notiz-/Aufgabenarbeit kann einen eigenen Arbeitschronikkanal besitzen, wird aber nicht als Dateiänderung ausgegeben.

Dateiänderungen anhand kontrollierter ThreadDesk-Dateivorgänge beziehungsweise beobachteter Inhaltsänderungen erfassen; technische Kopie/Empfang mit Originalherkunft und Empfangszeit unterscheiden. Ungeprüftes `atime` gilt nicht als Nachweis menschlichen Zugriffs.

Explizites „Datei öffnen“ kann „Öffnen erfolgreich veranlasst“ belegen; es beweist nicht, dass ein Mensch den Inhalt tatsächlich gelesen hat. Bewusst angeforderte Inhaltsausgabe kann einen belegten Abruf erfassen. Hintergrundvorschauen und technische Reads zählen nicht. Die Bedienoberfläche zeigt die genaue Ereignisart statt einer erfundenen Lesezusage.

Reine dynamische Lesewerkzeuge bleiben ohne fachliche Schreibeffekte. Protokollierte Benutzeraktionen wie `files.open` oder ein ausdrücklich angeforderter Inhaltsabruf erhalten einen eigenen deklarierten Effekt und Activitybeleg. Kein stilles Ändern der Aktivität durch `get_thread`, Graphquery oder Browserhover. Akteur und Ursprung aus dem tatsächlichen Aufrufkontext ableiten, keine frei behauptete Identität als Beweis übernehmen.

### Anzeige und Auswahl

Vorgeschlagene Modi: „Geändert“, „Geöffnet/abgerufen“ und „Dateiarbeit“. Im kombinierten Modus zählt der neueste belegte Zeitpunkt beider Kanäle; Tooltip und Inspektor nennen Kanal und Zeit. Dieser kombinierte Anfangsstandard ist ein konkreter Planvorschlag, kein alter bereits bestätigter Beschluss. Getrennte Modi erhalten die offene frühere Frage nach gleicher Gewichtung.

Feste Intervalle: ≤24 Stunden, >24 Stunden bis 7 Tage, >7 bis 30 Tage, >30 bis 90 Tage, älter und unbekannt. Die Skala hängt nicht vom gerade sichtbaren Teilgraph ab. Farbe und Helligkeit werden für Light/Dark abgestimmt; ältere Knoten bleiben lesbar, statt transparent zu verschwinden. Warn-/Fokusrahmen und Textetikett ergänzen Farbe. Palette erst nach Kontrast-/Farbenfehlsichtigkeitsprüfung endgültig festlegen; [D3 sequentielle Skalen](https://d3js.org/d3-scale-chromatic/sequential) sind ein geeigneter Ausgangspunkt.

Zeitwerte in UTC, lesbare lokale Anzeige mit Zeitzone, `as_of` und Aktivitätsrevision. Rollende 24 Stunden nicht „heute“ nennen. Zukunftszeitpunkte/Uhrsprünge diagnostizieren. Bestandsdaten mit nur `updated_at` ausdrücklich historisch ungenau oder unbekannt darstellen; keine künstlichen Arbeitsereignisse zurückfüllen. Projektaggregation zeigt „Aktivität in enthaltenen Objekten“ getrennt von direkter Projekt-/Dateiarbeit. Bei mehreren Anhängen wird nur das Maximum der für den Aufrufer autorisiert sichtbaren Dateiereignisse aggregiert; Tooltip und Inspektor nennen die konkrete Datei und den Kanal. Knoten ohne Datei bleiben im Dateimodus unbekannt, statt auf Status oder `updated_at` zurückzufallen.

## 8. Kleine Arbeitspakete und Zuständigkeiten

Jedes Pflichtpaket hat Gewicht 1. Fertig zählt nur mit belegter Abnahme; Fortschritt = abgenommene Pakete / 18. Dieser Planungsauftrag bedeutet noch keinen Implementierungsfortschritt.

| ID | ThreadDesk-Dateibereich / Arbeit | Abhängigkeit und Zuständigkeit | Konkretes Abschlusskriterium |
| --- | --- | --- | --- |
| B01 | Threadmanagement, UI-/CLI-Eingabe und Fehler: Revisions-/Operationsbindung | Backend/UI; Start | Zwei veraltete Ansichten überschreiben sich nicht; Entwurf/409, identischer Replay, geänderte Nutzlast; JSON/SQLite |
| B02 | Fachtransaktion und Eventgrenze: Commit vor Erfolgsevent | Storage/Backend; parallel B01 | Fehlgeschlagene Erstellung ohne Events; Erfolg einmal; Replay ohne Doppelevent; Listenerfehler korrekt eingeordnet |
| B03 | Command-/Funktionsmatrix und gemeinsame Registry | Verträge; Start, übernimmt B01/B02 | Alle Fachaktionen zugeordnet; Handler/Schema/Alias eindeutig; alte MCP-Namen kompatibel; keine doppelte Logik |
| B04 | Vollständige CLI/JSON und MCP-Adapter in ThreadDesk | Adapter; B03 | Gleiche Fachresultate/Fehler, Workspacebindung, Pagination, Statuslookup; echte Reads bleiben inert |
| B05 | End-to-End-Bedienmatrix über vorhandene KiraBridge | Integration; B04, pro Domäne fortschreiben | Native Teilmenge und sichtbarer CLI-Modus real belegt; keine fehlende UI-Fachaktion verschwiegen; keine KB-Codeänderung |
| B06 | TrashService-/Eigentums-/Referenzvertrag und Lebenszyklusmodell | Datenverträge; B03 | Objektarten, IDs, Generation, Revision, Restore-/Purgeauswahl und fehlende Referenzen festgelegt |
| B07 | JSON/SQLite-Lebenszyklus, Migration und Writerkompatibilität | Storage; B01/B02/B06 | move/restore atomar; Crash/Replay/alte Generation/Revision; alter permanent-delete-Weg kontrolliert migriert |
| B08 | Papierkorb-UI, Suche, Graphsichtbarkeit und Restore | UI/Queries; B07 | Normallisten ohne gelöschte Objekte; identische IDs/History/Beziehungen nach Restore; keine neue aktive Auswahl |
| B09 | Libraryreferenzen und ausdrücklich bestätigter Purge | Library/Trash; B07/B08 | Keine Original-/geteilte Blobkaskade; konkrete Preview; offene Handoffs blockieren; identischer Replay |
| B10 | Backup-/Migrationslisten und Room-/Server-Synctombstones | Daten/Sync; B07, vor Aktivierung B08/B09 | Restore erhält Trash; verspätetes Paket belebt nichts wieder; Delete/Edit/Restore-Konflikt sichtbar; alte Peers definiert |
| B11 | ActivityStore/-Service mit Dateiänderung und explizitem Zugriff | Daten/Activity; B02/B03 | Getrennte Kanäle, belegter Ursprung; technische Reads/Sync/Restore ohne neue Frische; JSON/SQLite gleicher Stand |
| B12 | Versioniertes Graphreadmodell und View-/Activitycommands | Graph/Verträge; B03/B08/B11 | Stabile IDs, Teilgraph/Filter, Activitymetadaten/as_of, gespeicherte Ansichten; v1-Kompatibilität definiert |
| B13 | Begrenzter Renderer-/Layoutspike auf echtem Desktop | Grafik; B12-Vertrag | Vergleichsbeleg samt WKWebView, Worker, GPUausfall, Offline, Größen/Lizenzen und endgültiger Pinentscheidung |
| B14 | Kleine Graph-Controller für Renderer/Layout/Selection/Inspector/Viewstate | Grafik/UI; B12/B13 | Übersicht, Suche, Nachbarschaft, Fixpositionen, gespeicherte Sichten; kein Fachzustand nur im Renderer |
| B15 | Zeitmodi, Legende, Listenparität, Tastatur/Reduced Motion/Kontrast | UI/Accessibility; B11/B14 | Beide Aktivitätskanäle korrekt, unbekannt/Uhr/Filter/DST-Ränder; ohne Farbe/GPU vollständig bedienbar |
| B16 | Anhänge/Zuordnungen, deterministische Beziehungen und Vorschlagsgrenze | Library/Graph; B09/B12/B14 | Datei am Ziel als echter Anhang; unklar zentral; bestätigte Zuordnung automatisch, semantische Änderung nur vorgeschlagen |
| B17 | Vollständige Fachabnahme und unabhängiges Review | Test/Review; B05–B16 | Jede Matrixzeile real über vorhandene Bridge bedient; Desktop/API-Parität; Konflikt, Replay, Offline, Restore und Neustart |
| B18 | Regulärer Merge, finaler Paket-/Desktopabgleich und Betriebsbeleg | Koordinator/Release; B17 + Pflicht-CI | Quell-/Paket-/Runtimepin belegt, getestetes Paket installiert, Nutzerworkspace erhalten; sauberer lokaler/Remote-main |

B01/B02 können parallel beginnen. B03/B04 bilden die gemeinsame Bediengrundlage. Papierkorb B06–B10 wird vor Produktaktivierung vollständig konsistent, inklusive Sync/Backup. Activity B11 und Graphspike können nach ihren Verträgen unabhängig vorbereitet werden. Neue Graphansicht folgt nach tragfähiger Daten-/Bediengrundlage. Semantisches Gedächtnis, Mobile-App und neue Fremdproduktentwicklungen sind keine versteckten zusätzlichen Baupakete.

## 9. Team, Git und Desktop dauerhaft gleich halten

Die aktuelle Nutzerregel steht in [AGENTS.md](../../AGENTS.md) und zusätzlich im erhaltenen bisherigen Hauptordner. Jede künftige ThreadDesk-Arbeit nutzt echte Teamaufträge mit Übernahme, Dateieigentum, 60-Sekunden-Rückmeldekontrolle, Belegen und unabhängiger Prüfung. Bestehende geeignete Worktrees weiterverwenden; fremde laufende Aufträge nicht überschreiben. Der gemeinsame Arbeitsspeicher bleibt Thread `188ce4729a62`.

Abgeschlossene Änderungen committen und pushen, Review und geltende Pflichtprüfungen abwarten, dann regulär nach `main` mergen. Kein Adminbypass und kein Merge unter falschem CI-Erfolg. Falls ein konkretes Gate blockiert, dessen Status mit Beleg nennen und den vorbereiteten Stand erhalten. Die vom Nutzer erteilte Mergeautorisierung muss für diesen Umfang nicht erneut eingeholt werden.

Für Laufzeitänderungen: endgültigen integrierten Quellpin feststellen, daraus Paket bauen, isoliert mit kopiertem Workspace prüfen, tatsächlichen Desktop bedienen, konkrete getestete Installation übernehmen und Source-/Paket-/Runtimeidentität unabhängig zurücklesen. Vorherige App und Daten wiederherstellbar erhalten. Commit-Push allein aktualisiert keine laufende Anwendung.

Für reine Dokumentations-/Regeländerungen wie diesen Auftrag: kein Binärneubau identischen Laufzeitcodes. Stattdessen paketierten Laufzeitinhalt gegen aktuellen Gitstand vergleichen, tatsächlichen älteren Buildpin nennen und fehlende Abweichungen belegen. Ein geändertes Dokument erzeugt keine neue implementierte Desktopfunktion. So bleibt der Funktionsstand gleich, während die Herkunft des bestehenden Pakets ehrlich sichtbar bleibt.

Pflicht-CI bleibt unverändert: zweimal Gesamtsuite einschließlich Browsern und keine ausgelassenen Abnahmetests; pausierte native Windowsentwicklung wird nicht wieder gestartet. Entwicklungsprüfungen nur für tatsächliche Änderungen, kein vorsorgliches Wiederholen bereits bestandener Tests. Neue Regressionsfälle richten sich auf reale Risiken: Stale-Edit, Rollbackevents, Trashgeneration/Referenzen, Tombstonereplay, echte Dateiaktivität, GPU-/Workerverlust und vollständige ChatGPT-Bedienung.

## 10. Was dieser Plan abschließend nachweist

Die konkreten Anforderungen wurden aus tatsächlich gelesenen Quellen konsolidiert. Aktuelle Grafiktechniken wurden anhand von Primärquellen recherchiert. Papierkorb, Zeitaktivität und vollständige Bedienung haben klar getrennte Fachverträge, ThreadDesk-Dateibereiche, Zuständigkeiten, Abhängigkeiten und Abnahmen. Die feste KiraBridge-Writegrenze bleibt ausdrücklich ausgewiesen.

Keine Produktfunktion wurde durch diesen Plan bereits implementiert; kein Nutzerinhalt wurde gelöscht, umorganisiert oder in private Originalvolltexte nach Git kopiert. Der anschließend ausdrücklich beauftragte Bibliotheks-/Such-/Dateimanager-Bauabschnitt folgt nun in Abschnitt 11; die historische Planungsabnahme wird dadurch nicht nachträglich als Umsetzung ausgegeben.


## 11. Aktueller Bauauftrag Bibliothek, Indexsuche und Graph-Dateimanager

Der neue Nutzerauftrag ergänzt diesen Plan statt einen parallelen Plan einzuführen. Verbindlich sind nun: echte zugängliche freigegebene Inhalte importieren, lokale Indexsuche mit hoher Priorität, Dateiverwaltung direkt im vorhandenen Graphen, erweiterbare Formate und sofortiger Bediennachweis über vorhandene KiraBridge. Eine neue Graphengine, semantische KI-Suche, Mobilanwendung und weitere früher zurückgestellte Produktideen gehören nicht zu diesem Bauabschnitt. Der vorhandene Graph wird für Dateinavigation erweitert.

### Bestand und Wahrheit über Originale

**Nutzerpräzisierung:** Maßgeblich ist der jeweils aktuelle autorisierte Dateibestand, der sich laufend ändern kann. 275 Dateien/23 Ordner sind ausschließlich historische Vergleichszahlen, kein festes Soll und keine Obergrenze. Jeder Lauf bekommt einen frischen Quellenstand mit Erfassungszeit und Fingerprints; neue/geänderte/umbenannte/fehlende Dateien als Delta führen. Eine Änderung während der Übernahme wird erkannt und als instabil beziehungsweise neue Version behandelt. Wiederaufnahme bleibt an ihren belegten Quellenstand gebunden; ein Folgelauf erfasst den aktuellen Stand neu.

Die historische Inventur enthält275Einträge und nennt23Ordner; viele Zeilen besitzen weder Originalbytes noch Hash oder individuelleQuellversion. Für jede Zeile getrennt erfassen: zugänglicheQuelle, tatsächlicherByteimport, Referenz-only, eindeutigerlokalerKandidat ohne historischenIdentitätsbeweis, Konflikt, ausdrücklicherAusschluss. Namens-/Größenübereinstimmung allein bestätigt nicht das historischeOriginal. Eine bestätigteÜbernahme braucht SHA256 der tatsächlichgelesenenQuelle und der gespeichertenKopie; Originale bleiben unberührt. FehlendeOriginale einzeln ausweisen, nicht durch neueDateien oder Referenzen ersetzen. Ursprüngliche sensitive/redaktierte Ausschlüsse bleiben geschützt.

Importe verwenden vorhandenenLibraryImporter/Receiver/CAS mit persistentenQuellen-/Dateibelegen. UnklareZuordnung geht in den vorhandenen zentralenEingang. GleicheInhalte werden als Dubletten markiert und können Blobs teilen, ohneDateirecords/Quellenzuordnungen automatischzulöschen. Wiederaufnahme derselbenOperation liefert ihrenBeleg oder setzt nur offeneEinträge fort. KeinBlindreplay historischerKiraBridge-Aufträge. PrivateOriginalinhalte und lokaleInventurpfade gehören nicht in öffentlichePrüfbelege.

### Erweiterte Funktionspakete mit sofortiger KiraBridge-Abnahme

Die folgende Reihenfolge konkretisiert B03–B05, B06–B12 und B16–B18 für den aktuellen Umfang. Keine zweiteModulverwaltung, keinzweiterDateispeicher und kein konkurrierenderSuchdienst. JederLIB-Punkt verlangt schon vorFertigmeldung Oberfläche/Fachschnittstelle UND realenautorisiertenBridgeaufruf plusReadback; Integration ist kein späteresRestpaket. GewichtejePaket1, fertig nur mitallen zugehörigenBelegen.

| Paket | Wiederverwendung und Dateieigentum | Abhängigkeit und Abnahme |
| --- | --- | --- |
| LIB01 Bestand und Importbelege | LibraryImporter/Receiver, bestehendeInventur; Quellen-/Importmodul | Historische 275 Zeilen als Vergleich nachvollziehbar; aktueller freigegebener Bestand je Lauf maßgeblich, erreichbare Originalbytes/konkrete Lücken getrennt; SHA256vor/nach, Zuordnungen/Originale erhalten, Dubletten ohneLöschung; Status überBridge lesen |
| LIB02 ErweiterbareFormatadapter | kleineAdapter für Klassifikation/Extraktion, vorhandenerImport | Verwalten/Index/Vorschau/externesÖffnen unabhängig ausgewiesen; keineSkript-/Makroausführung; proDateiTimeout/Größenlimit/Fehlerisolation; Formatliste überBridge |
| LIB03 VerbindlicherlokalerIndex | vorhandenerLibraryIndex+Suchprojektionen, SQLiteFTS5 | Name/Pfad/auslesbarerInhalt/Projekt/Thread/Graph; Teilbegriffe, Schreibvarianten, Typ/Datum/Projekt/Zuordnung; Treffer mitDatei-/KnotenIDs; echteNamens-/Inhaltssuche überBridge |
| LIB04 Dateiverwaltung | bestehendeCASRecords, kleinerLibraryFileService | Liste/Ordner/Sortierung/Info, mehrereAnhänge, rename/copy/move/assign mitRevision+Operation; Provenienz/Referenzen erhalten; jedeAktion überBridge samtReadback |
| LIB05 Popup und externesMacÖffnen | eigenerPreview-/Openadapter, vorhandenerGraphinspektor | ErsterDateiklick nurPopup, explizitererneuterKlick/Doppelklick/InAppöffnen; keineunbeabsichtigtenStarts; fehlenderHandler erklärt; zulässigerrealerBridgeOpen mitLaunchbeleg, keinmenschlichesLesenbehauptet |
| LIB06 Dateipapierkorb und Indexnachführung | kontrollierterDateilifecycle ausB06–B10, keineOriginalkaskade | Trash/Restore gleicheRecord-/KnotenIDs, Index/Ansichtaktualisiert; Replay/alteRevision/Neustart; Backup erhältLifecycle; BridgeTrash/Restore jeweils unabhängigzurücklesen |
| LIB07 DurchgehendeBedienung | dünneUI/API/MCP/CLIAdapter einerFachlogik | Original→Import→Index→Name/Inhalt→Graph→Popup→MacApp→rename/move→Index/Zuordnung→Trash/Restore→erneutfinden; jederentsprechendeBridgeaufruf echt; nativeVertragsgrenze benannt, sichtbareCLInachgewiesen |
| LIB08 Integration und Auslieferung | bestehendeTests/CI/Paketierung | GroßeDatei/unbekannt/keinHandler/Konflikt/Offline/Neustart/ältererIntelMac; zweiPflichtGesamtabnahmen+Review, Commit/Push/Merge, finalerDesktop-/GitPin undDatenerhalt |

### Formatumfang und sichere Rückfälle

Dokumente: PDF,DOC/DOCX,ODT,RTF,TXT,EPUB,HTML,Markdown. Tabellen:XLS/XLSX,ODS,CSV/TSV. Präsentationen:PPT/PPTX,ODP,KEY. Bilder:JPG,PNG,GIF,WEBP,TIFF,HEIC,SVG. Audio:MP3,WAV,FLAC,AAC,M4A,OGG. Video:MP4,MOV,WEBM,MKV,AVI. Quellcode/strukturierteDaten:PY,JS,TS,JSON,XML,YAML,TOML,SQL,LOG. Archive:ZIP,TAR,GZ,7Z. UnbekannteFormate werden soweit zulässig gespeichert/verwaltet, ohneunsichereVorschau oderAusführung.

Text/Quellcode wird nuralsDaten gelesen, HTML/SVGniemalsalsaktiveAnwendung eingebettet. OOXML/ODF/EPUBwerden mitgebundenemArchiv-/XMLbudget extrahiert; keineMakros/externenReferenzen. PDF benötigt einenbegrenztenParser; gescanntePDFs ohneOCR werden nicht alsvolltextindexiert bezeichnet. LegacyOffice,KEY,7Zoder nichtdekodierbareMedien können Metadaten/Standardprogrammfallback liefern. JedeFormatantwort sagt konkret, was verwaltbar,indexierbar,internvorschaufähigundexternöffnungsfähig ist. Parserfehler blockiertkeineanderenTreffer.

### Status und Evidenz

ProFunktion getrenntführen: vorhervorhanden, geplant, implementiert, gezieltgetestet, integrativgetestet und tatsächlichüberKiraBridgeerreichbar. EinTest mitMock-Open ist keinrealerMacprogrammstart; CodexPrincipal ist nicht automatisch einChatGPTPrincipal; einlokalerMCP-Test ist keinBridge-End-to-End. Verfügbarkeit ist erst nachkonkretemzulässigemAufruf undReadbackbelegt.


### Implementierungsstand des Bibliotheksabschnitts · 26. Oktober 2026

Der frühere Gesamtplan und seine zurückgestellten Themen bleiben erhalten. Die folgende Matrix betrifft ausschließlich den nun autorisierten Bibliotheksabschnitt. „Implementiert“ bedeutet Quellcode im aktuellen Integrationszweig; Installation, produktiver Datenimport und die ChatGPT-Identitätsprüfung sind eigene Abnahmeschritte.

| Funktion | Bereits vorhanden | Ergänzung jetzt implementiert | Geprüfter Stand / verbleibende Abnahme |
| --- | --- | --- | --- |
| Bibliotheksbytes und Empfang | CAS, ursprünglicher Importer, resumierbarer Dateiempfang | Aktuelle Quellenmanifeste, SHA vor/nach Veröffentlichung, Checkpoints, Wiederaufnahme, Dubletten und unveränderliche Quellversionen | JSON/SQLite und eigene Testdateien geprüft; **aktuelle freigegebene Originalquelle für produktiven Vollimport fehlt** |
| Bestandsabgleich | Historische Inventur mit 275 Einträgen/23 Ordnern | Einzelfallabgleich und getrennte Lücken/Kandidaten/Konflikte/Ausschlüsse | 24 lokale Kandidaten ohne historischen Identitätsbeweis, fünf Größenkonflikte, 238 im geprüften Umfang fehlende Originale, acht geschützte Ausschlüsse; keine Importerfolgsmeldung daraus |
| Lokale Indexsuche | Bestehende LibraryIndex-Schnittstelle | SQLite-FTS5, Inhaltsadapter, Namen/Pfade, Threads/Graph/Projekte, deutsche Varianten, Teilbegriffe und Filter | Suchtests und tatsächliche Bridge-Namens-/Inhalts-/Projektabfragen; keine allgemeine KI- oder Tippfehlerkorrektur behauptet |
| Quellenänderungen | Manueller Ordnerimport | Nur ausdrücklich registrierte Quellen beobachten; neue Versionen, fehlende Quellen und Nachführung mit festem Budget | Änderungen/Neustart/Metadatenersetzung gezielt getestet; lokaler Lauf mit 275 Dateien und 61 CLI-Aufrufen bestätigt automatische Änderungen/Neuzugänge, erhaltene Nutzernamen/-ordner und erhaltene Kopie bei fehlender Quelle; zusätzlicher Bridgebeleg offen |
| Formate | Vorherige Importklassifikation | Gemeinsame erweiterbare Registry mit getrennten Fähigkeiten; begrenzte Text-/Office-/Archiv-/PDF-Adapter | Metadatenrückfälle und Parserfehler geprüft; echte Bridge-Formatabfrage vorhanden; gefrorenen PDF-Worker im finalen Paket prüfen |
| Graph-Dateimanager | Bestehender Graph und Inspektor | Mehrere Anhänge, Dateiliste/Ordner/Sortieren/Info/Zuordnung, Popup, rename/copy/move | Browserfälle für DE/EN und API-Parität; KiraBridge-CLI-Aktionen mit unabhängigem Readback tatsächlich ausgeführt |
| Mac-Öffnen | Vorherige Downloadmöglichkeit | Explizite Aktion, LaunchServices-Handler, geprüfte schreibgeschützte benannte Kopie, dauerhafter Startbeleg | Tatsächliche TextEdit-Anforderung mit anschließendem Operationsreadback; kein menschliches Lesen behauptet; fehlender Handler/unklares Ergebnis gezielt getestet |
| Dateipapierkorb | Originale und gespeicherte Referenzen | Reversibler Record-Lifecycle mit Revision/Generation und gleicher ID; Graph-/Indexfilter, Restore | JSON/SQLite, Backup und echter Bridge-Trash-/Restore-/Suchablauf; keine endgültige Löschung angeboten |
| Gemeinsame Bedienlogik | Vorhandene CLI, MCP, lokale UI-Routen | LibraryApplication mit dünnen HTTP-/CLI-/MCP-Adaptern; Operationsbindung und paginierter Importstatus | Lokale Transportparität; realer sichtbarer Bridge-Ablauf mit 31 Aufrufen unter **codex** bestätigt; **ChatGPT-Principal nicht geprüft** |
| Integration und Desktop | Installierte App 0.1.2, älterer Laufzeitpin 07e10bf | Kandidat 0.1.3 vorbereitet | Finaler Review, Pflicht-CI zweimal, regulärer Merge und Paket-/Installationsidentität sind bis zum konkreten Releasebeleg offen |

Die nativen vorhandenen KiraBridge-Schreibverträge werden nicht still erweitert. Der dynamische Lesekatalog war bei der tatsächlichen Prüfung deaktiviert. Der autorisierte sichtbare CLI-Weg wurde unter der tatsächlichen Identität `codex` genutzt; daraus folgt keine bestätigte Bedienbarkeit aus einem anderen ChatGPT-Kontext. Der erste zusätzliche Großbestands-/Live-Source-Auftrag scheiterte vor dem Programmstart an einem KiraBridge-Terminaltimeout. Ein neuer, eigenständig quittierter Auftrag td-library-frozen-live-20261026-v2 wurde anschließend tatsächlich im sichtbaren Terminal ausgeführt: 275 eigene Dateien, 51 Aufrufe des gepackten Backends vom Quellpin 387a2eb, automatische Änderung/Neuzugang und Erhalt gespeicherter Kopien; max. 10.530 Bytes je Antwort, Exit 0 und verarbeiteter Completionbeleg. Auch dieser Nachweis betrifft den Principal codex. KiraBridge selbst wird dafür nicht verändert.

Importantworten und `import_status` liefern jetzt eine begrenzte Zusammenfassung ohne das vollständige Quellenmanifest sowie Dateiseiten mit `total`, `returned`, `next_offset` und Kürzungskennzeichen. Der Aufrufer folgt dem tatsächlichen `next_offset`. Der Extremtest traversiert alle 275 Einträge einschließlich langer Unicodepfade innerhalb des 30-KiB-Seitenbudgets. Ein lokaler Test dieses Budgets ersetzt den echten Bridge-Transportnachweis nicht.

Der reale bisherige Bridge-Ablauf verwendete eigene synthetische Dateien: Import → automatische Indexierung → Namens-/Inhalts-/Projekt-/Variantenabfragen → Knotendateiliste → Vorschauinformationen → TextEdit-Startbeleg und Operationsreadback → Kopieren → Umbenennen → Verschieben → Zuordnen → Papierkorb → Wiederherstellen → erneut finden. Unbekannte Formate blieben verwaltbar und wurden nicht gestartet. Die eigentliche Popup-Bedienung wurde separat im Browser geprüft; eine CLI-Vorschauantwort wird nicht als sichtbarer Popupbeleg ausgegeben.

Detaillierte stabile Befehlsverträge, Formatmatrix und Ressourcengrenzen stehen in [library-commands.md](../library-commands.md). Private Inventurpfade, Originalinhalte und vollständige Terminalverläufe bleiben außerhalb des Repositorys. Die eigens erzeugten Akzeptanzskripte sind `scripts/check_library_workflow.py` und `scripts/check_library_live_source.py`; ihre Ausgaben sind Testbelege und keine produktiven Nutzerdateien.

Versionswiederherstellung: Der unabhängige Schlussreview fand und korrigierte den Konflikt einer aktuellen Quellversion mit ihrem eigenen erhaltenen Vorgänger. Nur exakte IDs aus demselben bestätigten Source-Receipt erlauben diese Versionsüberlagerung; unabhängige Kopien und fremde Quellen bleiben Namenskonflikte. Sechs JSON-/SQLite-Regressionen prüfen Original-/Historienerhalt und die Konfliktgrenze. Der erweiterte Live-Source-Akzeptanzlauf enthält nun auch Trash/Restore nach einem Quellenversionswechsel.

Offene Formatabnahme KEY: Die bestehende private-Schlüssel-Schutzregel sperrt `.key` beim Import/Empfang. Der tatsächliche Formatkatalog nennt diese Admissiongrenze nun ausdrücklich (`import_allowed=false`, `secret_name`). KEY ist nicht vollständig unterstützt. Vor Freigabe werden echte geprüfte Keynote-Dateien und eine gemeinsam genutzte positive Inhaltsprüfung benötigt; keine pauschale Ausnahme für private Schlüssel. Diese Grenze bleibt neben aktueller Originalquelle und ChatGPT-Principal in der Restabnahme sichtbar.

Index-/Graph-Wiederaufnahme: Der aktive Hintergrundlauf repariert eine verlorene abgeleitete Suchdatenbank, migriert den alten JSON-Index und initialisiert ausschließlich bereits vorhandene CAS-Records ohne Indexmanifest. Er rekonstruiert fehlende Dateiknoten vor der Indexierung; reine Readtools und leere Profile schreiben dadurch nichts. Zwölf gezielte JSON-/SQLite-Fälle einschließlich echtem Backup/Restore, Original-/CAS-Erhalt und Record-Linkguards sind geprüft. Nach einer Reparaturstörung gilt ein 30-Sekunden-Retryabstand. Der finale gepackte Live-Source-Lauf verschiebt dafür nur seine eigene Test-Indexdatenbank samt Sidecars, startet den Backendprozess neu und prüft den automatischen Suchreadback.

### Graph-Lesbarkeit nach Bibliotheksintegration · Korrektur 0.1.4

Die installierte Ausgabe 0.1.3 (`c73d1f2`, PR 92) zeigte einen Bedienfehler: Der Dateimanager unter dem SVG ließ dem Graphen bei den geprüften Fenstergrößen nur 180 Pixel Höhe. Die feste SVG-Ansicht verkleinerte Beschriftungen auf ungefähr zwei Bildschirm-Pixel. Der Quellenstand allein und bestandene Dateifunktionstests waren deshalb keine ausreichende Sichtabnahme.

Die Korrektur ergänzt B14 und die Graph-Dateimanager-Abnahme: Graph als Hauptarbeitsfläche; schließbarer Seiteninspektor mit Auswahl-/Dateireiter; Dateien vor den aufklappbaren Such-/Ordnerfeldern; tatsächliche Bühnenmaße für Kamera und Einpassen; 14-Pixel-Titel und 16-Pixel-Auswahltitel; kollisionsfreie Titelplatzierung, getrennte Klickflächen, Suche/Typ-/Projektfilter und expliziter Auswahlfokus. Layout, Bildschirmgeometrie und Oberflächensteuerung sind getrennte lokale Module. Dateiänderungen erhalten Auswahl, Positionen und Bildausschnitt. Die Desktop-App startet maximiert.

Abnahme: dieselben 28 Knoten gegen unveränderten Vorherstand und Korrektur prüfen; bei 1440×900 und 1180×760 mindestens 60 Prozent der nutzbaren Höhe für den Graphen, mindestens die Hälfte der Titel in der geschlossenen Übersicht lesbar und keine Textkollisionen. Tatsächliche Schriftgröße über SVG-Bildschirmtransformation messen. Inspektor, Dateien, Vorschau, Umbenennen, Filter, Fokus und Fensteränderung bedienen. Bei 940×640 zusätzlich nachweisen, dass versetzte Titel keine fremden Knotenklicks abfangen. Danach unabhängiges Review, vollständige Pflicht-CI zweimal, regulärer Merge und Sichtprüfung des aus finalem Main gebauten Mac-Pakets einschließlich Datenerhalt. Bis zu diesem Nachweis gilt die Desktop-Korrektur als offen.

Dies erfüllt nicht B13/B15: Der Sigma-/Worker-Vergleich, gespeicherte Ansichten, vollständige Listenparität und die beiden Dateiaktivitäts-Zeitmodi bleiben ausdrücklich offen. Die hier gezeigten Farben bedeuten weiterhin Status, keine erfundene letzte Dateiarbeit. Die vorhandenen Datei-/Suchbefehle und KiraBridge-Transporte bleiben fachlich unverändert; eine reine Darstellungsprüfung belegt keine neue Bridge-Fachaktion.
