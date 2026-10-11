# P10-03: lesende Agent-Authority-Ansicht in ThreadDesk

Vorabvertrag auf ThreadDesk main d9c712a9ca2ef156d7189544e8a779e10814d731.
Auftrag: Agent Authority in die Produktphase bringen, anschließend „sinnvoll
weiter“. P10-02 ist mit PR42, Quellengegenprüfung WB1720, Mergegegenprüfung
WB1724 und Abschluss WB1726 abgeschlossen. Ohne abweichende Anzeigepräferenz
folgt eine lesende ThreadDesk-Verknüpfung im eigenen Checkout.

## Ergebnis und Grenzen

Ein normaler Link beim Whiteboard-Stand öffnet den vorhandenen deutschen
Beobachterbericht für genau den ausgewählten Thread. Der Bericht verwendet
unverändert Reader, Projektion und HTML-Renderer aus Agent Authority 0.3.0a2,
Quellencommit 35f592f0d8a9040ccb7c5f48cc22ac1b0c091729. Keine kopierte
Analysemethode, keine zusätzlichen Agentenentscheidungen oder Statusänderungen.

Der GET liest das gewählte JSON-Profil direkt, ohne Store-Konstruktor,
ThreadService, Aktivitätsmeldung, Threadwechsel oder Workspace-Renderer.
Thread-ID wird vor Dateizugriff geprüft. Nur die begrenzten Whiteboard-Dateien
werden analysiert, keine Threadtitel, Freitexte, Prompts oder Metadaten gezeigt.
Der Reader meldet fehlende/leere/fehlerhafte Archive weiterhin sichtbar.
SQLite wird nicht als JSON interpretiert. Falsche Paketversion, fehlendes
optionales Paket und ungültiges Profil erhalten feste übersetzte Meldungen;
keine Rohfehler oder Dateipfade gelangen in die Antwort.

Installation ist ein optionales Extra mit festem Git-Commit und Python >=3.12.
ThreadDesk ohne Extra behält seine Python->=3.9-Metadaten und startet weiterhin.
Der bereits vorhandene Server liefert HTML; kein neuer Hintergrunddienst,
Subprozess, automatischer Refresh oder automatischer Browserstart. GET schreibt
keinen Cache oder Bericht. Antwort: no-store, nosniff, no-referrer; vorhandene
Renderer-CSP bleibt erhalten. Kein Authentisierungs-/DLP-/Produktionsfreibrief.

D-012 bleibt: ThreadDesk hält Kontext; Agent Authority beobachtet/analysiert/
warnt. Keine Rechte-, Geheimnis-, Budget-, Freeze-, Lauf- oder Stopentscheidung.
Herkunft/Identität/Wirkung/globale Abdeckung bleiben UNBEKANNT. P6-Gesamtabnahme,
P4/RC-01..05/CB-01/OOS-021 und historische Herkunftsgrenzen bleiben offen.

## Dateivertrag

- Neu services/authority_preview.py: feste optionale Schnittstelle, nur lesend.
- ui/server.py: eigener GET und feste Fehlerantworten ohne Workspace-Aufruf.
- core/i18n.py und partials/whiteboard_stand.html: übersetzter normaler Link
  und Nichtverfügbarkeitsmeldungen.
- pyproject.toml: optionales authority-Extra mit festem Quellencommit.
- .github/workflows/tests.yml: Extra in den vorhandenen zweimaligen Tests.
- Neu tests/test_authority_preview.py und tests/test_authority_browser.py:
  reale Paket-/Route-/Profil-/Nebenwirkungs-/Browserprüfung.
- README.md, neue docs/AGENT-AUTHORITY-PREVIEW.md und dieser Vertrag.

Keine übrigen Quellen, alten Tests, Authority-Quellen oder historische Archive
ändern. Sauberer Branch codex/agent-authority-view-20261011 im eigenen Worktree.
Vor Implementierung Vertrag committen und pushen. Laufende ThreadDesk-Instanz
und schmutziger ursprünglicher Checkout werden nicht verändert.

## Abnahme und Nachweise

1. Bericht entspricht bytegenau dem vorhandenen Renderer; richtige Thread-
   und Profilauswahl, strukturelle Warnungen, keine privaten Canarys.
2. Baum vor/nach allen erfolgreichen und fehlerhaften GETs bytegleich;
   fehlendes Root wird nicht angelegt. Kein Service-/Store-/Aktivitätsaufruf.
3. Fehlpaket, falsche Version, SQLite, ungültiges Profil, ungültige ID,
   fehlender/leerer/defekter Verlauf: klare begrenzte Antwort ohne Rohfehler.
4. Tatsächlicher Browser folgt dem Link; breite/schmale Ansicht, Tastatur-
   Disclosure, Rücknavigation, keine Berichtsnetzressourcen prüfen.
5. Neue gezielte Tests und gesamte bestehende Suite einschließlich Browser
   zweimal. Private-Dateien- und JavaScript-Checks bleiben erfolgreich.
   Ausgangsfehler getrennt archivieren; keine alten Tests passend ändern.
6. Veröffentlichten Commit, PR und tatsächliche separate Quellenprüfung
   archivieren. Nur bei exaktem HEAD und grünen Prüfungen normal integrieren,
   kein Admin/Force; Squash/Tree/Parent/main und Push-Checks nachweisen.

Ein lesender Produktadapter, keine vollständige Paket-/Betriebsabnahme.

## Ergänzung vor Anpassung des Aktivitätslisteners

Der tatsächliche Browserlauf zeigte: Die normale Linkaktivierung meldet in der
vorherigen ThreadDesk-Seite einen allgemeinen Aktivitäts-POST. Deshalb wird
zusätzlich ui/static/app.js zugelassen: ausschließlich beim neuen markierten
Beobachterlink dessen Eingabeereignisse von reportActivity ausnehmen. Kein
globales Abschalten von Aktivität, kein Berichtsskript. Die Browserprüfung
fordert weiterhin genau den Berichts-GET und einen bytegleichen Datenbaum.
Diese Vertragsergänzung wird vor dieser zusätzlichen Codeänderung veröffentlicht.
