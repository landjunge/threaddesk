# ThreadDesk und KiraBridge Prüfbelege

Geprüft am 26. Oktober 2026: ThreadDesk `07e10bf`, KiraBridge-Adapterquelle `d2edeb6`. Drei tatsächlich übernommene Teamaufträge prüften Funktionen, dynamische Integration und Architektur. Diese Belege dokumentieren Diagnose und Planungsgrundlage; keine Produktreparatur oder Produktionsaktivierung.

- [Funktionsprüfung](functional-report.md): 68 unterschiedliche gezielte Fälle bestanden, einschließlich realem Chromium-Neustarttest. Die zuvor fehlende Testumgebung und ein Browser-Skip wurden gezielt aufgelöst; erste Ergebnisse bleiben im Bericht sichtbar.
- [Dynamische Integration](dynamic-report.md): 55 KiraBridge-Vertragsfälle und eine ThreadDesk-Annotationsprüfung bestanden; aktuelle Coverage und Discovery-Grenzen.
- [Architekturprüfung](architecture-report.md): Modulbefunde, Transaktionsereignisse und ausführbare Arbeitspakete.
- [Maschinenlesbare Zusammenfassung](checks.json): Quellpins, Grenzen, Zählungen und beobachtete Fehler.

Die Reproduktionen [veraltete Notiz](repro-stale-edit.py), [Rollback-Events](repro-rollback-events.py) und [Kataloggrenze](repro-tool-limit.py) arbeiten ausschließlich mit synthetischen Daten beziehungsweise Mocks. Die Notizreproduktion verwendet zwei HTTP-Testclients; sie ist kein Zwei-Fenster-Browsertest. Die Ausgabe ist ein bestätigter offener Fehler, kein bestandener Reparaturtest. Skripte sind Beobachtungsbelege und werden nach einer Reparatur in passende Regressionstests überführt.

Ausführung vom jeweiligen geprüften Repository mit explizitem `PYTHONPATH=src:tests` (ThreadDesk) beziehungsweise `PYTHONPATH=src` (KiraBridge) und einer geeigneten bestehenden Pythonumgebung; genaue Aufrufe stehen in den Berichten. Das unqualifizierte `python3` dieses Rechners ist 3.8 und ungeeignet. Keine vollständige Testsuite oder native Produktionsabnahme in diesem Auftrag.

Die Live-Abfrage des vorhandenen KiraBridge-MCP-Tools ergab `tools=[]`, `enabled=false`, `isError=false`. Das belegt deaktiviertes Opt-in und sagt nichts über eine danach mögliche Verbindungs-/Rechteprüfung. Der existierende gemeinsame Arbeitsspeicher wurde mit Revision 66 gelesen; keine konkurrierende Whiteboardinstanz angelegt.

Das [unabhängige Planreview](plan-review.md) bestätigt die Architektur ohne blockierenden Widerspruch. Der [Kontextspeicherbeleg](work-memory-receipt.json) dokumentiert späteres Append von Revision 67 auf 68 mit vorherigem Revisionslesen, stabiler Operation und unabhängigem Readback; bestehender Inhalt erhalten. Dafür wurde der schon vorhandene gepinnte ThreadDesk-MCP-Verwaltungsweg benutzt, keine neue Whiteboard-Methode implementiert.
