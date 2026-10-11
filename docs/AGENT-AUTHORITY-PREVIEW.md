# Agent Authority Preview

Öffne einen Thread in ThreadDesk und klicke beim Whiteboard-Stand auf
**Beobachterbericht öffnen**. Die deutsche Preview zeigt Beiträge, gemeldete
Aufgabenbezüge, strukturelle Warnungen und aufklappbare Eintragsbelege mit
SHA256. Die Zurück-Taste des Browsers führt zurück zu ThreadDesk.

Der Bericht liest ausschließlich das Whiteboard des bezeichneten Threads im
aktuell gewählten JSON-Arbeitsbereich. Er wechselt keinen Thread, aktualisiert
keine Aktivitätsdaten und schreibt keine Berichtsdatei. Jeder Aufruf liest
erneut; die angezeigte Seite aktualisiert sich nicht automatisch. Gleichzeitige
Änderungen können gemeldet werden; es gibt keine atomare Gesamtaufnahme.

## Optionale Einrichtung

In einer eigenen Umgebung mit Python 3.12 oder neuer, aus diesem Checkout:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install '.[ui,authority]'
.venv/bin/threaddesk ui
```

Das Extra installiert Agent Authority **0.3.0a2**, fest gebunden an
[Quellencommit 35f592f](https://github.com/landjunge/agent-authority-lab/commit/35f592f0d8a9040ccb7c5f48cc22ac1b0c091729).
Git und Netzwerk werden für diese Einrichtung benötigt. Zur Laufzeit ruft der
Bericht nur die Bibliothek auf, keine Shell/CLI und keinen externen Dienst.
Ein vorhandenes geprüftes 0.3.0a2-Wheel kann stattdessen in genau dieselbe
Umgebung wie ThreadDesk installiert werden. Das separat installierte
`agent-authority`-Kommando in einer anderen Umgebung reicht dafür nicht aus.

Ohne Extra startet ThreadDesk weiterhin. Fehlt das Paket, stimmt seine Version
nicht oder läuft ThreadDesk unter Python <3.12, meldet die Berichtsseite die
fehlende Einrichtung. SQLite-Arbeitsbereiche haben noch keinen Adapter; sie
werden ausdrücklich als nicht verfügbar angezeigt. Auf Plattformen ohne den
POSIX-Reader erscheint dessen begrenzter Bericht mit Plattformwarnung.

## Aussagegrenzen

Die Preview verwendet unverändert Reader, Projektion und HTML-Renderer aus
Agent Authority 0.3.0a2. Höchstens 10.000 JSON-Dateien mit jeweils 65.536 Bytes
werden geprüft; jeweils 20 Aufgaben-/Beitragszeilen werden angezeigt.
Auslassungen und Leseprobleme bleiben sichtbar. Ein unbekannter oder fehlender
Whiteboard-Verlauf erscheint als begrenzter Bericht und erzeugt kein Archiv.
Die Ansicht zeigt keine Threadtitel, Whiteboard-Freitexte, Prompts, rohen
Agenten-/Auftragsnamen oder frei gespeicherten Metadaten.

Ein Ergebnisbeitrag beweist keinen Aufgabenabschluss. Gespeicherte Herkunfts-
und Erfolgsmeldungen authentisieren nichts. Identität, Wirkung und globale
Abdeckung bleiben **UNBEKANNT**. Der Bericht beobachtet und warnt; er entscheidet
nicht über Rechte, Geheimnisse, Budget, Freeze, Ausführung oder Stopps.

Die HTML-Seite braucht keine Skripte, Bilder, Schriften oder Netzressourcen.
Sie übernimmt die feste CSP des Renderers; HTTP-Antworten sind `no-store` und
geben keinen Referrer weiter. Das ersetzt keine Zugriffsregel für ThreadDesk:
der vorhandene Server und seine lokale Bereitstellung bleiben maßgeblich.
Diese Preview ist keine allgemeine Produktions-/Sicherheitsfreigabe.
Historische P6-Gesamtabnahme, P4/RC/CB/OOS- und Herkunftsgrenzen bleiben offen.
