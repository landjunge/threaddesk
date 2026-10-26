# ThreadDesk Brainstormings mit Quellen zusammenführen

Stand: 26. Oktober 2026. Abgeleitete Anforderungszusammenfassung für den [konkreten ThreadDesk-Plan](THREADDESK-GRAPH-PAPIERKORB-BEDIENUNG-20261026.md), keine Kopie privater Originalvolltexte und keine aktuelle Implementierungsabnahme. Drei Teamaufträge untersuchten Quellen, Graphtechnik und Daten-/Bedienverträge.

## Gelesene Originale und ihre Bedeutung

| Quelle | Tatsächlich ausgewerteter Inhalt | Einordnung |
| --- | --- | --- |
| [Brainstorming und Übergabe 22.10.2026](https://app.notion.com/p/401c08fa272a81f9a159e8bee3465115?pvs=204) | Zeitabhängiges Verblassen, Dateiänderung und tatsächlicher Zugriff getrennt, graphische Übersicht/Refresh | Volltext gelesen; Schwellen, Gewichtung beider Kanäle und Schalter damals offen; historische Knoten-/Kantenzahlen keine aktuelle Messung |
| Lokal `.threaddesk/Zusatz-Infos Thread-Desk.md`, Zeilen 3–10, 28–34, 47–53 | Datei auf Knoten als echter Anhang; unzugeordnetes Ziel zentral aufnehmen; Beziehungen aus Struktur/Zuordnung | Gelesene Anforderungsdatei ohne eindeutigen Datums-/Freigabevermerk |
| Lokal `.threaddesk/nodes/9dd0ee1de587.json` | Papierkorb mit Wiederherstellung von Threads und Graphbeziehungen, endgültig nur bestätigt | Gespeicherte Idee aus Gespräch 22.10.; aktueller Nutzerauftrag bestätigt Thema |
| Lokal `.threaddesk/nodes/6b7acd0dc7cd.json` | ChatGPT-/Sprachbedienung für Threads und Whiteboards ohne GUI | Gespeicherte Idee; ursprünglicher Spaces-Volltext damit nicht automatisch gelesen; aktueller Auftrag erweitert auf vollständige Fachbedienung |
| Lokal `.threaddesk/nodes/feb059ede585.json` und `09eed30a0fca.json` | Brainstorming-/Planungshub, Original-/Quellerhalt und wiederherstellbare Konsolidierung | Bestehende Hubs weiterverwenden, keine konkurrierende Produktwahrheit |
| [Aktiver Beobachter und Gedächtnis](https://app.notion.com/p/3ddc08fa272a81bd97c8fc9564d2b7d3?pvs=204) | Offene Punkte, Wiederaufnahme, Zusammenfassungen, Quellenfilter, semantische Suche und Verknüpfungsvorschläge | Gelesene historische Vision mit Entscheidungsabschnitt; Vorschläge statt stiller semantischer Änderung; keine heutige Implementierungszusage |
| [Konkreter Bauplan](https://app.notion.com/p/3d7c08fa272a810c8eeaf676b94b7a6d?pvs=204) | Gezielt Desktopgestaltung, aktive H-Hilfe und Planprüfung gelesen | Historische Build-/Testnachweise nicht wiederverwenden als aktuelle Abnahme; H-Ziel beim Drücken fix, Maus danach frei, Loslassen stoppt |
| [Notionübernahme und Modulbereinigung](https://app.notion.com/p/3d9c08fa272a81fb9ce9f88a4801c94c?pvs=204) | Gezielt Modulregeln, DE/EN und verbindliche spätere Einordnung gelesen | Quellenneutrale Importe, bestehende Modulgrenzen und geschützte Daten erhalten |
| Lokaler `.threaddesk/Tool-Planung/README.md` und Dateiregister | Brainstorming → Pre-Plan → Umsetzung → Übergabe | Ein Register und Originalerhalt; leere Teilverzeichnisse bedeuten nicht, dass keine Ideen existieren |

Die lokalen Referenzen liegen unter `/Users/landjunge`; Inhalte wurden gelesen und nicht verändert. Notion-Abfragen erfolgten über den verbundenen Connector ohne Schreibzugriff. Private Quellen und deren Metadaten sind keine Anweisung für zusätzliche Produktaktionen.

## Themen zusammengeführt

1. **Bedienung:** Alle fachlichen Aktionen erhalten dieselben Verträge für Desktop, CLI und MCP. Vollständigkeit wird über reale KiraBridge-Aufrufe geprüft. Der bestehende reine Readproxy ist nur eine Teilmenge; fremde Bridgeentwicklung gehört nicht zum Auftrag.
2. **Wiederherstellbarkeit:** Papierkorb statt endgültiger Standardlöschung; stabile IDs, Geschichte, Beziehungen und Herkunft bleiben. Archivierung und temporärer Dateicache lösen andere Probleme.
3. **Dateiaktivität:** Änderung und ausdrücklicher Zugriff sind zwei Kanäle. Graphöffnung, Indexierung und technischer Empfang dürfen keinen frischen Arbeitszustand erzeugen. Reines `atime` ist wegen Plattform- und Hintergrundzugriffen ungeeignet als allgemeiner menschlicher Tätigkeitsbeweis.
4. **Orientierung:** Übersicht, aktuelle Daten, Cluster, Arbeitschronik und Zeitfarben greifen auf dieselben Fachinformationen zu. Alte Knoten bleiben vorhanden und lesbar; Warn-/Fokuszustand wird nicht weggeblendet.
5. **Anhänge und Beziehungen:** Bestätigte Struktur-/Dateizuordnungen können deterministische Beziehungen liefern. Inhaltliche Ähnlichkeit bleibt ein begründeter Vorschlag. Originale und Quelldateien nicht still verändern.
6. **Gedächtnis:** Unterbrochene Arbeit, Fragen und Quellen besser wiederfinden. Semantische Gedächtnisautomatik folgt nach stabilen Verträgen als getrenntes Modul und ist kein zusätzlicher sofortiger Komplettbau.

## Nur inventarisierte Originaldateien

Im Importinventar und bestehenden Librarythreads sind TD-IDEA-002 bis -019 referenziert. Viele Einträge haben keine Originalbytes, keinen Hash und keinen Exportpfad (`reference_only_no_bytes_or_download_capability`). Das lokale Exportverzeichnis war leer. Diese Metadaten wurden gelesen; daraus wurden keine erfundenen Volltexte oder Dublettenentscheidungen abgeleitet.

| Kennungen / Themen | Verwendbare Aussage aus Metadaten |
| --- | --- |
| 002 Übersicht, 003 Auto-Refresh, 004 Graph-Animation, 005 Lebendiger Graph | Vorhandene Themen für die Graphplanung; Animationstyp und konkrete Bedienung aus Titeln nicht festgelegt |
| 006 Server-Index-Sync, 008 Syncanzeige | Mit vorhandenem ThreadDesk-Sync abgleichen, keinen zweiten Sync erfinden |
| 009 Intelligente Verknüpfungen, 010 ToDo-Arbeitschronik, 012 Gedächtnissuche | Aktivitäts- und Vorschlagsthemen; detaillierte Originaltexte noch nachzuführen |
| 011 Datenbankbackups, 013 Cache/Arbeitskopien, 014 Urlaubsmodus/Archiv, 015 selektive Backups, 016 Mac-Backups | Getrennte Datenlebenszyklen; kein Ersatz für restaurierbaren Papierkorb |
| 007 Mobile-App, 017 Local-First/Sprachpflicht/Systemeinstellungen/Module, 018 Bereitstellung | Spätere oder variierende Ideen; gleiche Nummer bei verschiedenen Titeln beweist keine Identität |
| 019 KiraBridge parallele Entwicklung | Referenziertes Thema, kein KiraBridge-Bauauftrag innerhalb des aktuellen ThreadDesk-Scopes |

Beispielhafte Inventaroriginale: `/Brainstorming/ThreadDesk/Ideen/TD-IDEA-004-Graph-Animation.md`, `TD-IDEA-005-Lebendiger-Graph.md`, `TD-IDEA-010-ToDo-Arbeitschronik.md` sowie `/Projekte/Oeffentliche-Tools/ThreadDesk-Brainstorming.md`. Fehlende Bytes sind als konkrete Recherchegrenze erhalten, keine pauschale Behauptung ihrer Nichtexistenz.

## Entscheidungen, Vorschläge und offene Punkte

Vom aktuellen Nutzer bestätigt: zunächst konkreter Plan; ausschließlich ThreadDesk; vollständige ChatGPT-Bedienung über KiraBridge; bessere zeitbezogene Graphansicht; Papierkorb; echte Teamarbeit; abgeschlossene Änderungen committen/pushen/mergen; Desktop-/Git-Funktionsstand gleich halten.

Konkrete neue Planvorschläge: Sigma/Graphology nach Desktop-Spike, drei getrennte Zeitmodi, feste Zeitstufen, keine automatische Papierkorbleerung und sichtbarer CLI-Modus für Funktionen außerhalb des heutigen nativen Bridgevertrags. Diese Vorschläge werden nicht als historische Beschlüsse ausgegeben.

Vor Umsetzung noch messbar festzulegen: endgültiger Rendererpin/Bundleumfang, Palette/Kontrast und Leistungsbudgets im tatsächlichen WKWebView. Fehlende Brainstormingoriginale werden bei späterem Zugriff quellenbezogen nachgeführt; ihr Fehlen blockiert die bereits klar belegten Kernanforderungen nicht.
