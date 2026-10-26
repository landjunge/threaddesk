# ThreadDesk Graphansicht und zeitliche Arbeitsnähe

Recherche am 26. Oktober 2026. Session `/root/graph_research`. Nur Quellenprüfung und Plan; keine Implementierung, kein Benchmark, keine installierte App verändert. Geprüfter ThreadDesk-Fachstand `07e10bf` im vorhandenen Worktree `codex2-file-receiver-20261024`.

**Einordnung nach Quellenabgleich:** Die Technikwahl und Primärquellen gelten als Recherche. Der unten erhaltene erste Aktivitätsvorschlag wird durch Abschnitt 7 des [konkreten Plans](../plans/THREADDESK-GRAPH-PAPIERKORB-BEDIENUNG-20261026.md) ersetzt: tatsächliche Dateiänderungen UND ausdrücklich veranlasste Dateizugriffe getrennt zeigen; Statusänderungen sind keine Dateiaktivität. Dieser Recherchetext ist kein zweiter maßgeblicher Aktivitätsvertrag.

## Ausgangslage im Code

`src/threaddesk/ui/static/map.js:113–180` berechnet das Layout im UI-Thread: 420 Iterationen mit paarweiser Abstoßung aller Knoten. Die Abstoßung hat damit pro Iteration quadratischen Aufwand. Danach entstehen mehrere SVG-Elemente pro Knoten/Relation; Klick-/Tastatur- und Draghandler liegen ebenfalls pro Knoten an (`:455–521`). Das ist eine konkrete Skalierungsgrenze; ohne Messung keine Behauptung, ab welcher Knotenzahl die App tatsächlich stockt.

Die vorhandene Karte besitzt schon Pan/Zoom, Drag, Typformen, Statusmarken, Keyboard-Auswahl, Detailansicht und Threadlinks. Diese Fähigkeiten bleiben erhalten. Farben kodieren heute Status (`map.js:48–60`); Typformen, Glyphen und Marken geben weitere Signale. Zeitfarben dürfen den Status nicht still umdeuten.

`api/service.py:268–298` liefert `threaddesk.graph.v1` mit Knoten, Relationen, Zählung und Typ-/Statusfiltern. `KnowledgeNode` hat `created_at`, `updated_at`, Revision und Metadaten (`core/models.py:204–233`), aber kein semantisch definiertes `last_worked_at`. `GraphEvent` besitzt entity_id, revision und occurred_at (`:270ff`); bestehende Fachereignisse sind wiederverwendbar. Das alte Datum ist nicht automatisch ein Beleg tatsächlicher Arbeit.

Tauri ist auf Version 2 gepinnt; das Appbundle nennt macOS11 als Minimum. Die tatsächlich verfügbare GPU-/WebView-Achse wird deshalb gemessen, nicht aus dem Betriebssystemnamen geraten.

## Recherche und Technikwahl

**Vorgeschlagene Zieltechnik: Sigma.js4 plus Graphology und ForceAtlas2 im Worker.** Dies ist eine Empfehlung mit Abnahmegates, keine bereits bewiesene ThreadDesk-Leistung. Aktuelle Sigma-Dokumentation nennt v4, konkret4.0.3; Graphology0.26.0 ist dort der dokumentierte Partner. Abhängigkeiten bei Umsetzung exakt pinnen, lokal bündeln und Lizenztexte mitliefern; keine Laufzeit-CDNs.

| Kandidat | Quellenbeleg und Eignung | Entscheidung für ThreadDesk |
| --- | --- | --- |
| Sigma.js4 / Graphology | MIT, WebGL2-Renderer, vanilla-JS geeignet, Graphology als Datenstruktur; aktuelle Styles unterstützen Formen/Schichten, Labels und Interaktionen. Layout und Renderer sind getrennt. | Erste Wahl für eine große, erkundbare Wissenskarte; vorhandene Domänendaten bleiben auf dem Server. Genauen Bundleumfang und WKWebView-Verhalten messen. |
| Graphology ForceAtlas2 | Eigene Worker-API mit start/stop/kill. Barnes-Hut kann die Abstoßung von O(n²) auf O(n log n) reduzieren; explizit einschalten, nicht als Default voraussetzen. | Layoutarbeit aus UI-Thread lösen; feste Startpositionen/Seed und gespeicherte Koordinaten erhalten. Nach Stabilisierung stoppen. |
| Cytoscape.js3.34.4 | Aktuelle Releaseübersicht nennt3.34.4. MIT, viele graphische Interaktionen/Styles/Algorithmen, Canvas-Basis und Layout-Extensions. Ein WebGL-Preview wurde2025 angekündigt; diese alte Previewseite allein beweist nicht heutigen vollständigen Featurestand. | Gute Alternative, wenn compound nodes und umfangreiche direkte Bearbeitung wichtiger werden als große Übersicht. Nur im Spike vergleichen, keinen zweiten großen Renderer dauerhaft pflegen. |
| Cosmograph/Cosmos | Aktuelle Anbieterunterlagen beschreiben GPU-beschleunigtes Layout/Rendering. Lizenzseite nennt nichtkommerzielle Nutzung frei, kommerzielle Nutzung gesondert; verschiedene Namens-/Versionsstände nicht pauschal als MIT behandeln. | Keine Standardabhängigkeit ohne konkrete Paket-/Lizenzprüfung. Keine Preise oder kommerziellen Bedingungen aus alten Suchtreffern übernehmen. |
| WebGPU | WebKit dokumentiert Unterstützung in Safari26 seit15.09.2025, auch auf Sonoma/Sequoia. Somit ist die Aussage „macOS15 unterstützt kein WebGPU“ falsch. Browserunterstützung ist keine Zusage für das tatsächlich verpackte WKWebView/HW-Profil. | Kein zwingender Unterbau des ersten Releases. Optionaler späterer Layoutbeschleuniger nach Featureprobe; WebGL2-Ziel und fachliche Bedienbarkeit bleiben unabhängig. |
| D3 Farb-/Skalenmodule | D3 stellt sequentielle und wahrnehmungsnahe Viridis-Skalen bereit. | Nur nötige Skalenmodule oder lizenzkonform definierte Farbwerte nutzen; nicht die gesamte D3-Bibliothek für fünf Farbstufen hinzufügen. |

Primärquellen, jeweils am26.10.2026 geprüft:

- [Sigma Einstieg und dokumentierte Version](https://www.sigmajs.org/get-started/quickstart/): v4.0.3, Graphology0.26.0; eine lokale Bundleintegration ist möglich, CDN-Beispiele sind keine Betriebsanforderung.
- [Sigma Homepage und MIT-Lizenzverweis](https://www.sigmajs.org/), [aktuelle Paketmetadaten](https://github.com/jacomyal/sigma.js/blob/main/packages/sigma/package.json), [Rendererquellcode](https://github.com/jacomyal/sigma.js/blob/main/packages/sigma/src/sigma.ts): `getContext("webgl2")` belegt den tatsächlichen Renderingunterbau.
- [Graphology ForceAtlas2](https://graphology.github.io/standard-library/layout-forceatlas2.html): Worker-Lifecycle und Barnes-Hut-Option; [Graphology-Lizenz](https://github.com/graphology/graphology/blob/master/LICENSE.txt).
- [Sigma Performanceleitfaden](https://www.sigmajs.org/how-to/technical/performance/): Kosten von Antialiasing, Transparenz, Kantengeometrie und Picking; daraus folgt kein fixer FPS-Wert für ThreadDesk.
- [Cytoscape offizielle Dokumentation](https://js.cytoscape.org/), [aktuelle Releases](https://github.com/cytoscape/cytoscape.js/releases), [historischer WebGL-Previewartikel](https://blog.js.cytoscape.org/2025/01/13/webgl-preview/).
- [Cosmograph Anbieterübersicht](https://cosmograph.app/docs-general/), [Lizenzbedingungen des Anbieters](https://cosmograph.app/licensing/). Keine Empfehlung zur kostenpflichtigen Nutzung in diesem Plan.
- [WebKit Safari26](https://webkit.org/blog/17333/webkit-features-in-safari-26-0/): WebGPU und Verfügbarkeit; kein Rückschluss auf ungeprüfte App-WebViews.
- [D3 sequentielle Skalen](https://d3js.org/d3-scale-chromatic/sequential): Viridis ist eine wahrnehmungsnahe Skala.
- [WCAG2.2 Farbe und Textkontrast](https://www.w3.org/TR/WCAG22/), [WAI Nichttextkontrast](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast): Farbe nicht als einziges Signal; Text in der Regel4.5:1, bedeutungstragende UI-/Grafikindikatoren3:1 zu angrenzenden Farben, jeweils mit den normativen Ausnahmen.

## Konkrete bessere Ansicht

Standard ist eine ruhige zweidimensionale Arbeitskarte mit drei Bereichen: oben Suche/Projekt/Typ/Status/Zeitfenster, mittig Graph, seitlich vollständiger Inspektor. Unten steht die aktuelle Zeit-/Farblegende. Keine dauernd springende Simulation und kein obligatorischer dreidimensionaler Raum.

- Übersicht zeigt Projekte/Cluster und gut lesbare Hauptknoten; Zoom und Auswahl öffnen Details. Labels nach Priorität und verfügbarer Fläche; ausgewählter/fokussierter Treffer behält seinen Titel.
- Suchtreffer auswählen, zum Knoten springen, Nachbarschaft1/2Schritte zeigen, Pfad/Beziehungsart erklären, Auswahl isolieren und wieder Gesamtansicht herstellen.
- Projekte zuerst anhand echter Zuordnungen gruppieren. Optionale erkannte Communities ausdrücklich als rechnerische Gruppierung kennzeichnen; räumliche Nähe erfindet keine semantische Beziehung.
- Koordinaten und fixierte Knoten als eigene Ansichtseinstellungen speichern; Filteränderung berechnet nicht jedes Mal alle Positionen neu. Verdeckte Daten bleiben außerhalb der Auswahl und der Ergebniszählung nachvollziehbar.
- Gespeicherte Sichten mit Scope, Filtern und Zeitmodus; Deep Links binden echte Objekt-ID und Schema-/Viewversion, keine flüchtige Canvasposition.
- „Status“ und „Zuletzt bearbeitet“ als benannte Farbmodi. Im Zeitmodus zeigt die Füllfarbe die Arbeitsnähe; Typform und Statussymbol bleiben. Projekt-/Akteursfarben nur als gesonderter wählbarer Modus.
- Gleichwertige filter-/sortierbare Listenansicht und DOM-Inspektor mit echter Tastaturbedienung. GPU-Knoten sind keine barrierefreien DOM-Controls; nicht tausende unsichtbare Tabstops erzeugen. Roving-Fokus/Listenwahl, sichtbarer Fokus und Screenreadertexte verwenden.

## Ursprünglicher Aktivitätsvorschlag vor dem Quellenabgleich

Neues fachliches Readmodell `last_worked_at` bezeichnet den letzten erfolgreich committeden inhaltlichen Arbeitsvorgang, z.B. Notiz-/Beschreibungsänderung, Aufgabenstatus, Entscheidung, Ergebnis oder expliziter Whiteboard-Arbeitsbeitrag. Es wird aus erlaubten Ereignisklassen abgeleitet und mit `activity_kind`, Objekt, Akteur/Instanz, Revision und Herkunft erklärbar. Öffnen/Lesen, Zoom/Drag, Cache-/Indexaufbau, Backup und Sync-Empfang sind keine neue Arbeit. Ein echter empfangener fremder Arbeitsvorgang behält seine geprüfte Originalzeit; Empfangszeit getrennt führen.

Vorschlag für erste feste Stufen: ≤24Stunden,1–7Tage,8–30Tage,31–90Tage, älter; zusätzlich „unbekannt“. Neueste Einträge erscheinen hell/warm am Ende einer Viridis-Skala, ältere dunkler/kühler. Die Beispielsammlung `#440154 → #3b528b → #21918c → #5ec962 → #fde725` ist keine abschließende kontrastgeprüfte UI-Palette. Für dunklen und hellen Hintergrund sind kontrastfeste Umrandung/Statuszeichen nötig; alte dunkle Knoten dürfen nicht verschwinden. Zeittext und Legende transportieren dieselbe Information.

Skalendomäne bleibt bei Filterung stabil: ein alter Knoten wird nicht plötzlich „heiß“, weil neuere ausgeblendet wurden. Server liefert `as_of`, UTC-Zeitwerte und eine Aktivitätsrevision; Darstellung verwendet lokale Zeitzone mit eindeutigem Tooltip. „Heute“ als Kalenderdatum muss DST/Zeitzone beachten und ist nicht synonym zu24Stunden. Uhrsprünge/Zukunftszeitpunkte und ungültige Daten erhalten einen Diagnose-/Unbekanntstatus, keine künstliche Frische.

Bestandsdaten mit nur `updated_at` dürfen als „letzte gespeicherte Änderung, historisch nicht genauer auflösbar“ angeboten werden; niemals erfundene Arbeitsereignisse nachträglich anlegen. Direkte Aktivität und Projektaggregation getrennt ausweisen: „Projekt selbst bearbeitet“ vs „Aktivität in enthaltenen Aufgaben“. Restore, Import oder Sync verändern diese Historie nicht auf jetzt. Ein Nachtfading ist eine Darstellung anhand `as_of`, keine Schreiboperation.

## Modulplan mit messbarer Abnahme

| ID | Dateibereich und Abhängigkeit | Arbeit und Abschluss |
| --- | --- | --- |
| G01 Aktivitätsvertrag | `core` plus neues `services/activity`, Speicherprotokolle; nach Commit-/Revisionsreparatur | Ereignisklassen, last_worked_at, unbekannt/legacy und Aggregation definieren; JSON/SQLite gleicher Readstand. Replay/Sync/Restore/Reads erzeugen keine künstliche neue Aktivität. |
| G02 Graph-Readmodell | `services/knowledge`/Graph-Query plus CommandRegistry; nach G01 | Versionskompatibles Graphsnapshot mit Filtern, Activity-Metadaten, stabile IDs, Revision, as_of, Limits und Ansichtspagination/Teilgraphzugriff. Bestehendesv1 erhalten oder Migration explizit. |
| G03 Technischer Spike | neues UI-Modul `static/graph/renderer`, isolierte Fixtures; nach G02-Vertrag, ohne Produktivdaten | Sigma4/Graphology/Worker lokal bündeln. Gegen aktuelle SVG-Baseline und Cytoscape-Kandidat mit denselben Daten messen; reale WKWebView, Chromium und GPU-Ausfall prüfen. Ergebnis samt Paketgrößen/Lizenzen dokumentieren, erst dann endgültig pinnen. |
| G04 Kartenbedienung | `map.html`, kleine Controller/Selection/Layout/Renderer-Dateien | Suche, Filter, Fokus/Nachbarschaft, fixierte Positionen, Cluster/Labels, Inspektor und gespeicherte Ansichten; keine Fachlogik in GPU-Renderer. Alle bestehenden Links/Keyboardfälle bleiben. |
| G05 Zeitmodus und Zugänglichkeit | eigenes `activity-colors`/Legende, Listentabelle | Feste erklärbare Skala, unbekannt, Mode-Switch, Uhr-/Filterrandfälle, Statussymbol, Fokus, Farbenfehlsichtigkeit und Light/Dark-Kontrast prüfen. Detail/Listenbedienung vollständig ohne Farbe und ohne GPU. |
| G06 Vollständiger ChatGPT-Zugang | ausschließlich ThreadDesk-CommandSpecs/MCP | graph.query/get_node/neighbors/path, activity.query, graph-view.list/save/apply/get_state/focus_node als vorgeschlagene fachliche Operationen registrieren. Jeder verfügbare UI-Fachvorgang hat gleichwertigen API-Befehl; graph.view-Änderung beeinflusst echte verbundene Oberfläche nachvollziehbar, auch bei keinem angeschlossenen UI expliziter Status. Keine KiraBridge-Quelländerung im Auftrag. |
| G07 Integration | gemeinsame TD-Tests, Bundle/Desktop, nach G01–G06 | Echte Desktopbedienung, UI-/MCP-Parität, Offlinebetrieb, Kontextverlust, Worker-Cleanup, Datenerhalt und Versionsabgleich aus finalem Quellpin. Merge/Paket/Installation sind getrennt nachzuweisen. |

Vorgeschlagene Benchmarkziele, noch ungemessen: Fixtures100/1000/10000Knoten mit je angemessenen sparsamen Beziehungen; zusätzlich ein dichter Stressfall, lange Labels, isolierte Komponenten und Sternstruktur. Auf dem tatsächlichen Ziel-Mac für1000Knoten erste bedienbare Sicht≤2s, p95Pan-/Zoomframe≤33ms und Auswahlfeedback≤100ms anstreben; im10kFall degradiertes Level-of-Detail statt eingefrorener UI. Hardware, Anzahl sichtbarer Labels/Kanten, Pixelratio, Memory, Initialisierung, Layoutkonvergenz und Energie im Beleg führen. Ziele nach Spike anhand gemessener Hardware verbindlich festlegen; keine Werbeaussage „beliebige Graphgröße“.

WebGL2-Probe und Runtimefehler führen zu klarer Meldung plus zugänglicher Liste/kleinem SVG-Teilgraph. GPU-Kontextverlust kann wiederhergestellt werden, darf Datenzustand nicht ändern. Worker stop/kill beim Verlassen, keine Endlossimulation. Layout- und GPUarbeit nicht als inhaltliche Aktivität loggen. Volle Graphbearbeitung bleibt über Befehle/Inspektor möglich, selbst wenn die Grafik degradiert ist.

## Einordnung und offene Entscheidungen

Nur ThreadDesk wird umgesetzt. Die vollständige ChatGPT-Bedienbarkeit über vorhandene KiraBridge wird anhand realer Discovery und Befehlsaufrufe abgenommen. Wo das vorhandene Bridge-Protokoll eine fachliche Write-Funktion nicht transportieren kann, ist das eine externe Integrationsabhängigkeit; nicht durch unzulässige Readannotation, direkten DB-Zugriff oder heimliche KiraBridge-Änderung umgehen.

Entscheidungsvorlage: Sigma4/Graphology/Worker als Zielkandidat, klarer Zeitmodus mit belastbarem Aktivitätsmodell, zuerst gute2D-Übersicht und Listenparität. Bundleumfang, tatsächliche WKWebView/WebGL2-Leistung und Palette sind vor Umsetzungsgate offen. Keine Demo-/Cloudgrafik, neuen Benutzerkonten oder bezahlten Fremddienste erforderlich.
