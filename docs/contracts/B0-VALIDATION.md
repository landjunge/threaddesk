# B0 — Prüfung des Vertragsentwurfs

Stand: 3. Oktober 2026. Bezug: [`company-execution.v1-draft.1`](company-execution-v1.md).
Status: **Entwurf und begrenztes Referenzmodell geprüft; B0 nicht vollständig
abgenommen, keine Produktfunktion implementiert.**

## Reproduzierbarer Lauf

Aus dem Repository mit Python 3.10 oder neuer; nur Standardbibliothek:

```sh
python3 docs/contracts/check_execution_model.py
```

Das Programm verändert keine Dateien, führt keine Netzaufrufe aus und benötigt
keine Zugangsdaten. Bei einer Regelverletzung im unveränderten Modell oder einem
nicht erkannten absichtlichen Fehler endet es mit Fehlerstatus. Die JSON-Ausgabe
enthält bei einem erkannten Fehler die kürzeste gefundene Gegenbeispielfolge.

| Prüfung | Ergebnis am 03.10.2026 |
| --- | --- |
| Vollständige Erkundung des begrenzten Modells | 2.420 erreichbare Zustände, 8.694 Übergänge; keine Invariantenverletzung |
| Gezielte Fehlervarianten | Alle fünf erkannt |
| Ausdrückliche Reihenfolgeszenarien | Alle vier bestanden |
| Prozessabschluss | Exit-Code 0 |

Diese Zahlen gehören ausschließlich zum mitgelieferten Modell. Sie sind keine
Zahl bestandener Browser-, Integrations- oder Sicherheitsprüfungen am Produkt.

## Erkannte Gegenbeispiele

| Absichtlich eingeführter Fehler | Gefundene Folge | Verletzte Regel |
| --- | --- | --- |
| Gemeinsame Budgetprüfung überspringen | Aufruf 1 hält 8, Aufruf 2 hält ebenfalls 8 bei Limit 10 | `shared_money_limit` |
| Aktuelle Berechtigung bei Zulassung ignorieren | Intent → wirksamer Entzug → Reserve → Bestätigung → Zulassung | `admission_after_control_barrier` |
| Unklaren Ausgang nach Timeout freigeben | Reserve → Zulassung → Crash → automatische Geldfreigabe | `unknown_or_live_attempt_lost_reservation` |
| Unklaren Aufruf nach Wiederanlauf erneut senden | Zulassung → Crash → Wiederanlauf → automatischer Versandversuch | `automatic_resend_after_unknown` |
| Storno-Tombstone vergessen | Intent → Crash/Abbruch → Storno kommt zuerst an → verspätetes Reserve öffnet erneut | `late_reserve_reopened_tombstone` |

Die Fehlervarianten prüfen, dass die Überwachung auf diese konkreten Verletzungen
anspricht. Sie beweisen weder Vollständigkeit des Modells noch Fehlerfreiheit
einer späteren Implementierung.

## Vier ausdrückliche Szenarien

1. Zulassung vor bestätigtem Entzug: der bereits zugelassene Aufruf kann einmal
   versenden. Ein späterer Entzug behauptet nicht, diesen Versand verhindert zu haben.
2. Bestätigter Entzug vor Zulassung: selbst bei vorhandener Reservierung ist die
   neue Zulassung nicht mehr erreichbar.
3. Crash nach Zulassung, vor tatsächlichem Versand: Ausgang bleibt unklar und
   die volle Reservierung von 8 bleibt gebunden; Wiederanlauf sendet nicht erneut.
4. Endgültige Abrechnung von 2 nach Reservierung von 8: nur der ungenutzte Rest
   wird frei. Eine zweite Reservierung von 8 ergibt genau 10 Gesamtverpflichtung.

## Annahmen und Prüfgrenzen

Das Modell enthält genau zwei Aufrufe, ein Konto mit Limit 10, Höchstkosten 8
und endgültige Kosten 2. Es untersucht vertauschte Reserve-/Stornonachrichten,
wirksamen Entzug, Freeze, Ausfall einer Pflichtquelle und einen Crash mit
Wiederanlauf aus demselben intakten Journal. Ein einzelner Modellschritt ist
atomar. Wirksamer Entzug und Zulassung teilen eine geordnete Koordinatorfolge.
Rechte werden im Modell nicht wieder erteilt; die Quelle kommt nicht zurück.

Mehrere Intents dürfen gleichzeitig offen sein. Das ist eine bewusst großzügige
Abstraktion der geplanten Koordinatorserialisierung; sie prüft den gemeinsamen
Ledger auch bei überlappender Nachrichtenzustellung. Crash und konservative
Klassifizierung werden als ein Schritt zusammengefasst. Eine erfolgreiche
Abrechnung wird als kombinierter, bestätigter Zustandswechsel dargestellt.

Nicht dargestellt oder bewiesen sind insbesondere:

- reale Transaktionen, Dateisystem-/Datenbank-Dauerhaftigkeit, Journalverlust,
  alte Backups, mehrere aktive Controller oder sichere Epochwechsel;
- verlorene Settle-Antworten, mehrere Budgetkonten, Periodenwechsel, Preise,
  Anbieterabweichungen, Fristen, beliebig viele Aufrufe oder Fortschrittsgarantien;
- Identitätsprüfung, DPoP, Replay-Schutz, kryptografische Signaturen,
  Berechtigungsmodelle, Geheimnisschutz und authentische Raumverwaltung;
- tatsächlicher Netzwerkversand, Provider-Abrechnung, Browserbedienung,
  Medienerzeugung, Nutzerinstallation und native Plattformen.

Die im Vertrag beschriebenen Verfahren außerhalb dieses Modells benötigen
eigene Reviews und später echte Integrations-/Fehlereinbringungstests.
**T01–T22 aus GOLDENRULES bleiben Produkt-Abnahmefälle mit offenem Nachweis.**

## Quellabgleich und nächster Abschluss

Der Vertrag wurde gegen die in Abschnitt 1 fixierten Stände von ThreadDesk,
4AllPass und TollGate abgeglichen. Bestehende Handoff-/Return-Verträge,
Authority Event v1, Tresor-Kryptografie und laufender Broker bleiben unverändert.
Der bisherige TollGate-Aufrufzähler wird nicht als Geldbudget ausgegeben.

Vor einer Umsetzung sind das Identitäts-/Transportprofil, der 4AllPass-ADR für
Executor und selektiven Zugriff samt Recovery, die Raumautorität, die gesicherte
Journal-/Checkpoint-Spezifikation und der erste technisch begrenzte
Anbieteradapter zu prüfen. **B0 bleibt bis dahin ein prüfbarer Entwurf.**

Grok bearbeitet die übergebene Browser-/E2E-/Medienaufgabe. Aktive Voice-Hilfe und
native Mac-/Windows-/Linux-Builds bleiben gemäß Nutzerentscheidung nachgeordnet.
