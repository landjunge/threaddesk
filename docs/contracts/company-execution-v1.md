# B0 — Vertrag für kontrollierte Firmenaufrufe

Stand: 3. Oktober 2026. Protokollkennung: `company-execution.v1-draft.1`.
Status: **prüfbarer Entwurf, kein laufendes Produktprotokoll**. Diese Datei
konkretisiert B0 aus [GOLDENRULES.MD](../usability/GOLDENRULES.MD). Die dortigen
Produktentscheidungen bleiben maßgeblich. Ein Draft darf nicht als produktives
v1 ausgehandelt werden. Änderungen dieses Entwurfs erhalten eine neue Draft-ID.

Grok Build bearbeitet nach bestätigter Übergabe die vorhandene Browserausgabe,
Nutzer-E2E-Prüfung, Reparaturen und Hilfe-/Medienkette. Dieser Entwurf verändert
weder deren Produktpfade noch Tresor-Kryptografie, Broker oder TollGate-Code.

## 1. Abgleich und Aufteilung

Geprüfte Quellen am 03.10.2026:

| Quelle | Befund und Konsequenz |
| --- | --- |
| ThreadDesk `1de98700bbb6b14f32edde94a2fdabe7e3fa2338`, `services/handoff_contract.py` und `return_contract.py` | Handoff v1 ist untrusted Arbeitskontext, `ran=false`, `sent=false`; Return v1 ist `delivered/unverified`. Beides bleibt unverändert und verleiht keine Rechte. |
| ThreadDesk `docs/authority/authority-event-v1.schema.json` | V1 hat feste Felder und Typen. Neue Versand-/Journalzustände werden nicht hineingeschmuggelt. Abschnitt 10 beschreibt den geplanten separaten v2-Vertrag. |
| 4AllPass `47cc823d36f7731001a83f7fbda87d38ccc8e9b4`, `docs/capability-contract-v1.md`, `capability-interface.md`, `security-boundary.md` | 4AP-CAP-1 ist Konzept, kein Netzwerkprotokoll. Der laufende Broker kann nach Allow Raw-Secret liefern; mediated ist gesperrt. Dieser Entwurf aktiviert keinen dieser späteren Wege. |
| TollGate `d07c3ffb7513473a3de1c87bd01e9a1c9ea39c85`, `src/tollgate/usage_ledger.py` | Tagesaufrufzähler ist kein Geldjournal. Insbesondere darf dessen Tagwechsel-Reset nicht auf offene Geldreservierungen übertragen werden. |

Die frühere offene Wahl des Schlüsselwegs wird für das **neue Firmenprofil**
durch GOLDENRULES eingeengt: ein gesondertes 4AllPass-Ausführungsmodul setzt das
Geheimnis ein. TollGate entscheidet weiterhin über Ausführungs-/Geldpolitik;
4AllPass erweitert keine TollGate-Erlaubnis und führt dessen Budget nicht nach.
Der bestehende CAS-Server bleibt blind. Kein FastAPI-Tresorserver erhält
Klartextgeheimnisse, Vault Keys, PRF-Ausgaben oder Firmen-Ausführungsschlüssel.

| Beteiligter | Maßgeblicher Zustand | Darf nicht |
| --- | --- | --- |
| 4AllPass Firmen-Kontrollmodul | bestätigte Person/Gerät/Agent, Eintragsfreigabe, Delegation, Firmenmitgliedschaft | Budget erhöhen; private Tresore aufgrund einer Firmenrolle öffnen |
| zuständige Raumverwaltung | authentischer Mitgliedschaftsstand und Rollen des Raums | Eintragsrechte oder Geld schaffen |
| 4AllPass Executor mit einem aktiven Koordinator | geordnete Befehle, aktuelle Wirkungsrevisionen, Versandzulassung und einmaliger lokaler Versand | Budget oder fremde Rechte selbst erfinden |
| TollGate | Budgethierarchie, Limits, Freeze, Reservierung und Abrechnung | Schlüssel erhalten, Tresor öffnen oder Rechte erweitern |
| ThreadDesk | Auftrag, gewünschte Sichtbarkeit, importierte Nachweise und Ergebnisprüfung | über Import, Whiteboard oder lokalen Rollenstring Ausführung autorisieren |

## 2. Gemeinsame Darstellung und Bindung

Ein Ausführungsbereich `realm_id` gehört genau einer Firma, einem aktiven
Koordinator und einer maßgeblichen TollGate-Stelle. Hierarchische Budgetkonten
einer Reservierung liegen gemeinsam in deren Transaktionsdomäne. Eine Firma
kann nicht durch einen zweiten Bereich dieselbe Geldgrenze erneut vergeben.
Mandant, Gegenstellen und Vertrauensanker werden administrativ gebunden, nicht
aus Client-URLs übernommen. Erste Ausgabe: kein automatisches Failover.

Alle IDs sind zufällige, nicht semantische Referenzen mit mindestens 128 Bit
Entropie. Textkennungen sind case-sensitive; keine automatische Normalisierung
fremder IDs. Zeitstempel: UTC, RFC-3339-Form mit `Z`; für Fristen zählt die
zuständige Stelle, keine Client-Uhr. Geldbeträge und monoton steigigende
Sequenzen sind dezimale JSON-Strings ohne Vorzeichen, Exponent oder führende
Nullen (außer `"0"`), geprüft als nichtnegative Integer. Keine Float-Arithmetik.
Ein Budget benennt Währung und feste Untereinheit; keine stille Umrechnung.

Unbekannte Versionen, unbekannte Pflichtzustände, doppelte JSON-Feldnamen,
ungültige Unicode-Werte, übergroße Objekte und unerwartete Felder werden
abgelehnt. Größenlimits werden pro Nachrichtentyp fest konfiguriert. Die
Serialisierung für Bindungsdigests folgt RFC 8785; Zahlen außerhalb des exakten
JSON-Zahlenbereichs werden nicht als Number übertragen. Ein Digest ist kein
Signatur- oder Herkunftsbeweis. Digests von Anfrageinhalten bleiben im
geschützten Journal und werden nicht öffentlich als erratbare Prompt-Fingerprints
exportiert.

Jede Dienstnachricht trägt `protocol`, `message_id`, `realm_id`,
`coordinator_id`, `coordinator_epoch`, `operation`, `operation_id` und
`payload`. Antworten tragen dieselbe `operation_id`, `status`, `reason_code`
und eine Referenz auf das dauerhaft gespeicherte Ergebnis. Das Konto bzw. die
Dienstidentität kommt aus dem authentisierten Kanal, nie allein aus diesen
Feldern. Dienstaufrufe verwenden TLS mit gegenseitiger Identitätsprüfung und
fest gebundenen Gegenstellen. Schlüssel hierfür sind von Tresorschlüsseln getrennt.

Eine Betriebsepoch ist kein kurzlebiges Lease und kein Freibrief für automatischen
Leaderwechsel. Ein normales Wiederanlaufen bleibt am selben dauerhaft bestätigten
Journalstand. Ersatz des Controllers benötigt gesonderte Aufnahme, Abgleich und
Schlüsselrotation entsprechend GOLDENRULES.

## 3. Identität, Freigabe und Auftrag

### Geräteaufnahme und Besitznachweis

`Enrollment` bindet `company_id`, `person_id`, `device_id`,
`device_key_ref`, `device_key_generation`, `approved_by`, `revision`,
`status` und `confirmed_at`. `device_id` ersetzt nicht ThreadDesks
`instance_id`; die ausdrückliche Zuordnung wird gesondert gespeichert.
Passwort/Kontotoken allein darf keine Firmenaufnahme bestätigen. Ein zuvor
vertrauenswürdiges Gerät oder der überprüfte Firmen-Recovery-Weg bestätigt sie.

Ein handelnder Agent bekommt eine eigene `agent_id` und Schlüsselbindung mit
Bezug auf Person und zugelassenes Gerät. Derselbe Anzeigename ist keine
Identität. In der ersten Ausgabe bleibt Unterdelegation ausgeschlossen.

Für einen künftigen OAuth-basierten Zugang ist **DPoP nach RFC 9449** der
vorgesehene Standardbaustein für den Besitznachweis; er ist noch nicht vorhanden.
Vor Verwendung sind zugelassener Aussteller, feste Audience, Algorithmenliste,
Bestätigung der Schlüsselbindung und Widerrufsprüfung zu spezifizieren und im
zuständigen 4AllPass-ADR zu genehmigen. Pflichtprüfungen umfassen insbesondere
Signatur, `typ`, `htm`, `htu`, `iat`, `jti`, Server-Nonce und `ath` sowie
Bindung an das tatsächlich zugelassene Geräte-/Agenten-Schlüsselpaar.
Neuer HTTP-Versuch: neuer Proof, gleiche fachliche Aufruf-ID. Eine kopierte
Bearer-Sitzung plus Gerätekennung ist kein Ersatz.

DPoP beweist weder Personenidentität noch ein schadsoftwarefreies Gerät und
signiert nicht den gesamten Request-Body. Deshalb bleiben Aufnahme, aktuelle
Freigabe und die folgende serverseitige Anfragebindung eigene Anforderungen.
Dieser Entwurf baut keinen neuen OAuth-/OIDC-Provider in den Tresorserver.
Solange das Transport-/Identitätsprofil nicht genehmigt und getestet ist,
bleibt der Firmenweg **gesperrt**; kein eigener Ad-hoc-Signaturersatz.

### Maßgebliche Datensätze

| Datensatz | Pflichtinhalt |
| --- | --- |
| `Grant` | `grant_id`, `revision`, `company_id`, `person_id`, erlaubte Geräte-/Agentenbindungen, `entry_ref`, `credential_generation`, erlaubte Secret-Nutzung, `budget_policy_ref`, optionale `room_id`, Zeitfenster, Agentennutzung, Status |
| `Membership` | ausstellende Firmen-/Raumautorität, Subjekt, Bereich, Rolle, Revision, Status; keine lokale rooms.json als Autorität |
| `Delegation` | `delegation_id`, Revision, verantwortliche Person, handelnder Agent, Gerät/Schlüsselgeneration, Grant/Revision, `task_id`, `run_id`, begrenzte Aktionen, Laufzeit, Budgetpolitik-Referenz, `subdelegation=false`, Status |
| `BudgetPolicy` | in TollGate: Revision, Firma, zugelassene Ausführungsparameter, Währung/Einheit, Konten-/Periodenregeln, Limits, Freeze, Status |
| `Attempt` | `call_id`, kanonischer Inhaltsdigest, vollständige gebundene Identitäts-/Grant-/Delegation-/Mitgliedschaftsrevisionen, Task/Run, Eintrag/Generation, Adapter/Preisbasis, technische Höchstkosten, Budgetentscheidung, aktueller Zustand |

Freigabe zur Secret-Nutzung und TollGate-Ausführungsgrenzen werden geschnitten,
nicht vereinigt. Eine Freigabe trägt nur die Budgetpolitik-Referenz, keine vom
Client editierbare Bilanz. TollGate bestimmt die vollständige relevante
Kontenhierarchie selbst. Eine fremde oder weggelassene übergeordnete Grenze ist
kein alternativer Aufrufweg.

Der Client sendet `call_id`, Grant-/Delegationsreferenz, `task_id`, `run_id`
und strukturierte erlaubte Operationsparameter. Er darf keine Preisgrundlage,
Kontenliste, bestätigte Identität, Auth-Header oder freie Ziel-URL vorgeben.
Der Executor validiert und friert den kompletten tatsächlich auszuführenden
Aufruf ein: Firma, Akteure, Gerät, Eintrag/Generation, Anbieter/Operation/Modell,
relevante Parameter und Payload, Adapterversion sowie maximale abrechenbare
Einheiten. Darauf beruhen Digest und Kostenbeleg. Änderungen erfordern einen
neuen bewusst zugelassenen Versuch. Kein späteres Nachladen veränderbarer
Prompt-/Dateireferenzen unter demselben Digest.

Auftragstext bleibt untrusted Inhalt. Er belegt keinen Allow-Entscheid. Kein
automatischer Aufruf infolge eines Whiteboard-Beitrags oder Return-Imports.

## 4. Dauerhafte Zustände und Idempotenz

| Koordinatorzustand | Bedeutung | Erlaubte Folgezustände |
| --- | --- | --- |
| `INTENT` | geprüfte Anfragebindung vor jedem Reserve-RPC dauerhaft gespeichert | `RESERVED`, `CANCELLED_NO_SEND` |
| `RESERVED` | TollGate-Reservierung nachgewiesen; noch keine Versandzulassung | `ADMITTED`, `CANCELLED_NO_SEND` |
| `ADMITTED` | endgültige einmalige Versandzulassung dauerhaft gespeichert | `DISPATCH_ATTEMPTED`, `OUTCOME_UNKNOWN` |
| `DISPATCH_ATTEMPTED` | Versandversuch begonnen; Annahme durch Anbieter nicht daraus ableitbar | `PROVIDER_ACCEPTED`, `OUTCOME_UNKNOWN`, `SETTLED` |
| `PROVIDER_ACCEPTED` | Anbieterannahme belegt; endgültige Kosten können noch fehlen | `OUTCOME_UNKNOWN`, `SETTLED` |
| `OUTCOME_UNKNOWN` | Wirkung oder Kosten unklar; kein automatischer Wiederholungsversand | `SETTLED` nach belastbarer Klärung |
| `CANCELLED_NO_SEND` | dauerhaft gegen jede spätere Zulassung gesperrt | keine Wiederaufnahme; separater Status der Ledger-Stornobestätigung |
| `SETTLED` | tatsächliche endgültige Kosten in TollGate verbucht | keine zweite Abrechnung; Korrektur nur mit eigenem Beleg-/Incident-Verfahren |

Ein vor `INTENT` abgelehnter Aufruf erhält einen Deny-Nachweis und wird niemals
für diese Kennung zugelassen. `ADMITTED` ist bewusst **nicht** „Anbieter
angenommen“ oder „erfolgreich“. Nach `ADMITTED` wird auch bei unbekanntem
Nichtversand konservativ gebunden gehalten.

TollGate führt pro `(realm_id, call_id)` eine unveränderliche Bindung und den
Zustand `HELD`, `CANCELLED`, `SETTLED` oder `DENIED`. Dieselbe Operation/ID mit
identischem Inhalt liefert ihr bisheriges Ergebnis; anderer Inhalt liefert
`IDEMPOTENCY_CONFLICT`. Ein Retry ersetzt keine verweigerte Freigabe. Ein
`GetAttempt`-Aufruf liest nur Status; er löst weder Versand noch Reservierung aus.

Terminale Einträge einschließlich **Storno-Tombstones für noch unbekannte IDs**
werden nicht mit einer Reservierungs-TTL gelöscht. Archivierung muss die
Wiederholungssperre erhalten. Nachrichten einer alten stillgelegten Epoche
werden vor jeder Wirkung abgewiesen.

## 5. Geldjournal und Befehle

`Reserve(call_id, binding_digest, authorization_ref, quote_ref)` wird nur vom
gebundenen Koordinator angenommen. TollGate prüft aktuelle eigene Politik,
ermittelt alle Konten/Perioden und setzt **in einer Transaktion** für jedes Konto:

`bereits verbucht + alle offenen Höchstbeträge + neuer Höchstbetrag <= Limit`.

Ohne belastbare Quote für alle Kostenbestandteile kein `HELD`. Rundung erfolgt
bei Obergrenzen nach oben. Provider-/Modell-/Preisbasis und technische Limits
müssen zur eingefrorenen Anfrage passen. Schätzwerte genügen nicht. Ein freier
Text „höchstens 1 Euro“ ohne technisch durchgesetzte Begrenzung ist keine Quote.

Die Quittung enthält `reservation_id`, `call_id`, Bindungsdigest,
`policy_revision`, Konten-/Periodenreferenzen, Währung/Einheit und gebundenen
Höchstbetrag. Neue Geräte, neuer Tag und Prozessneustart erzeugen keine weitere
Geldstelle. Alte offene Posten bleiben ihrer Periode zugeordnet. Obergrenzen
ohne Periodenwechsel werden zusätzlich mitgeführt.

`CancelNoSend` benötigt die authentische Referenz auf ein bereits dauerhaftes
`CANCELLED_NO_SEND` des zuständigen Koordinators. Es schreibt einen terminalen
Tombstone auch dann, wenn `Reserve` noch gar nicht angekommen ist. Späteres
`Reserve` derselben ID bleibt gesperrt. Bei unbekannter Antwort fragt der
Koordinator Status ab bzw. wiederholt exakt denselben Stornobefehl. Er nimmt
eine Rückbuchung niemals nur wegen RPC-Timeout an.

`Settle` benötigt eine zugelassene Aufruf-ID, bestätigte endgültige Abrechnung,
eindeutige `settlement_id` und die unveränderte Reservierungsbindung. Erst wenn
alle abrechenbaren Teile endgültig geklärt sind, werden tatsächliche Kosten
genau einmal auf alle betroffenen Konten gebucht und übrige Bindungen frei.
Ein Modelltext oder bloßer HTTP-200 ist kein Kostenbeleg. Bei Betrag über der
Quote: Abweichung dauerhaft dokumentieren, betroffenes Budget sperren, keine
fiktive Kürzung der Rechnung. Eine solche Anbieterabweichung verletzt die
Voraussetzung der harten Kostenzusage und ist ein Incident.

Limit-Senkung unter bestehende Verpflichtungen löscht weder Kosten noch
Reservierungen; neue Aufrufe werden verweigert. Automatisches Entsperren durch
eine neue Periode ist bei einem Incident oder beschädigtem Journal verboten.

## 6. Versandzulassung und Widerruf haben eine Reihenfolge

Es gibt einen serialisierten Befehlsweg pro Realm. **Jeder** wirksame
Freigabeentzug, Geräte-/Agentenentzug, Firmen-/Raumaustritt, Freeze und jede
sonstige Änderung ausführungsrelevanter Politik muss diesen Weg benutzen.
Ein unabhängiger Admin-Endpunkt darf nicht „wirksam widerrufen“ bestätigen.

Die zuständige Quelle prüft Änderungsrechte und speichert zuerst den gewünschten
neuen Stand als `PENDING_EFFECT`. Sie darf ihn sofort zur zusätzlichen
Ablehnung verwenden. Bestätigt wirksam ist er erst mit einem dauerhaften
Koordinatorbeleg. Ein laufender zuvor geordneter Aufruf kann noch zugelassen
werden; erst die später bestätigte Barriere bildet die harte Grenze.

Unter einer gemeinsamen Serialisierung erfolgt:

1. aktuellen Quellenstand und authentische Revisionen lesen; widersprüchliche,
   fehlende oder nicht zuordenbare Stände verweigern;
2. `INTENT` dauerhaft protokollieren;
3. bei TollGate atomar reservieren; Antwort verifizieren und `RESERVED`
   protokollieren;
4. vor endgültiger Zulassung alle benötigten Rechte, Fristen und Sperren erneut
   prüfen; Quellenrevisionen an den eingefrorenen Versuch binden;
5. `ADMITTED` mit monotoner `admission_seq` und enger Versandfrist dauerhaft
   committen; erst danach ist ein einziger lokaler Versandversuch zulässig.

Der gleiche serialisierte Weg verarbeitet eine Sperre: gewünschte Revision
authentisch prüfen, erforderliche TollGate-Sperre dauerhaft setzen, dann
`CONTROL_EFFECTIVE` mit `barrier_seq` und Effektivstand committen. Erst danach
geht `EFFECTIVE` an die Quelle/den Nutzer. Teilfehler liefern `PENDING` oder
`UNKNOWN`, niemals eine optimistische Erfolgsbestätigung. Bei einem Wiederanlauf
wird die fehlende Bestätigung mit derselben Änderungs-ID aufgelöst.

Eine Zulassung nach der Barriere muss deren Zustand beachten. Bei Entzug ist
sie abgelehnt. Eine Zulassung davor kann noch versenden und Kosten erzeugen;
die Anzeige sagt „bereits zugelassen/in Bearbeitung“. Revisionen dürfen keine
alten Grants wieder gültig machen. Re-Grant benötigt neue ausdrückliche Freigabe
und neue Bindungen; ein alter Versuch wird nicht wieder aufgenommen.

Langsame Dienstaufrufe halten den Realm nicht unbegrenzt fest: feste interne
Fristen, danach kein neuer Versand und Versuch konservativ abbrechen/klären.
Währenddessen kann Widerruf sichtbar ausstehend sein. Es gibt keine unbelegte
Zusicherung einer maximalen Widerrufslatenz bei ausgefallenen Diensten.

## 7. Lokaler Versand und Wiederanlauf

`ADMITTED` erzeugt keine transportable Client-Capability und keinen extern
aufrufbaren Send-Endpunkt. Nur der aktive Prozess erhält ein einmaliges
flüchtiges Versandrecht für genau die gebundene Anfrage. Der Adapter legt
`DISPATCH_ATTEMPTED` dauerhaft ab, bevor er die Netzwerkoperation beginnt.
Automatische Transport-Retries und Redirects sind aus. Verpasste Versandfrist
stoppt den Versuch; unklarer Verlauf bleibt finanziell gebunden.

Nach Crash werden `ADMITTED`, `DISPATCH_ATTEMPTED` und nicht endgültig
abgerechnete Anbieterannahmen zu `OUTCOME_UNKNOWN`; kein automatisches Replay.
Vor Zulassung verbleibende Versuche werden dauerhaft auf `CANCELLED_NO_SEND`
gesetzt und über `CancelNoSend` abgeglichen. Ein erneuter Nutzerwunsch hat eine
neue ID und benötigt eigene Rechte-/Geldprüfung. Falls Provider-Idempotenz später
verwendet wird, braucht sie einen eigenen Adapterbeleg einschließlich ihres
Gültigkeitsfensters; sie wird hier nicht vorausgesetzt.

Der Neustart ist zunächst `RECOVERING`: Quellenrevisionen, Sperren, Journal und
TollGate-Posten abgleichen. Bei fehlendem/älterem Journal, unbekannten Epochs,
Rücksprung der Kontrollstände oder möglichem zweiten aktiven Executor bleibt
er `BLOCKED`. Ein altes Backup kann dies nicht selbst als frisch attestieren.
Alte Provider-Schlüssel eines ersetzten/kopierten Executors müssen ungültig sein,
bevor ein Ersatz bezahlte Aufrufe übernehmen darf.

## 8. Verbindliche Fehlersemantik

| Reason-Code | Bedeutung | Automatische Folge |
| --- | --- | --- |
| `IDENTITY_UNVERIFIED` / `DEVICE_REVOKED` | Aufnahme/Schlüsselbeweis fehlt oder ist entzogen | kein Anbieteraufruf |
| `GRANT_DENIED` / `MEMBERSHIP_DENIED` / `DELEGATION_DENIED` | notwendige aktuelle Berechtigung fehlt | kein Anbieteraufruf |
| `STALE_REVISION` / `EPOCH_MISMATCH` | veralteter oder fremder Wirkungsstand | neu authentisch abgleichen; denselben Versuch nicht umdeuten |
| `UNBOUNDED_COST` / `QUOTE_STALE` | belastbare aktuelle Obergrenze fehlt | kein Reserve/Versand |
| `BUDGET_EXCEEDED` / `FROZEN` | TollGate verweigert | kein alternativer Schlüssel oder anderes Budget |
| `IDEMPOTENCY_CONFLICT` | bekannte Kennung mit anderem Inhalt | ablehnen und protokollieren |
| `DEPENDENCY_UNAVAILABLE` / `JOURNAL_UNAVAILABLE` | erforderlicher Nachweis nicht erreichbar | keine neue Zulassung |
| `OUTCOME_UNKNOWN` | Zulassung/Versand oder Kosten nicht sicher geklärt | Status lesen, Bindung halten; kein blindes Wiederholen |
| `ACCOUNTING_MISMATCH` | Abrechnung widerspricht verbindlicher Quote | Incident und Sperre |

Fehlerantworten enthalten keine Geheimnisse, Payloads, Provider-Auth-Header oder
internen Dump. Nichtberechtigte erhalten keine Auskunft über fremde Einträge.
Eine Netzwerkfehlermeldung ist nicht automatisch ein fachliches Deny und kein
Nachweis des Nichtversands. Die UI unterscheidet abgelehnt, ausstehend und unklar.

## 9. Geordnete Beispielszenarien

| Fall | Reihenfolge und erwarteter Zustand |
| --- | --- |
| Erfolg | INTENT → Reserve/HELD → RESERVED → ADMITTED → DISPATCH_ATTEMPTED → belegte Annahme → endgültiges Settle. Restbudget erst bei belegter Abrechnung frei. |
| Zwei Geräte, je maximal 8 bei 10 frei | Beide dürfen INTENT haben. TollGate lässt nur eine gleichzeitige HELD-Reservierung zu. Identität und Herkunft ändern die gemeinsame Grenze nicht. |
| Entzug gewinnt | Reserve → CONTROL_EFFECTIVE → Versuch erneut prüfen → CANCELLED_NO_SEND → Ledger-Tombstone. Kein Anbieteraufruf. |
| Zulassung gewinnt | ADMITTED(seq 10) → CONTROL_EFFECTIVE(seq 11). Der frühere Versuch kann Kosten erzeugen; jeder neue Zulassungsversuch nach 11 ist verweigert. |
| Reserve-Antwort verloren | INTENT/Reserve-RPC → Timeout → dauerhaft CANCELLED_NO_SEND → CancelNoSend. Bis zur Ledger-Bestätigung keine angenommene Freigabe des Geldes. |
| Storno überholt Reserve | Ledger speichert zuerst CANCELLED für unbekannte call_id; verspätetes Reserve bleibt terminal abgelehnt. |
| Crash nach ADMITTED, vor tatsächlichem Send | Neustart OUTCOME_UNKNOWN, volle Bindung bleibt. Keine erneute automatische Send-Operation, auch wenn tatsächlich nichts ankam. |
| Anbieter antwortet, Settle-Antwort verloren | identische settlement_id abfragen/wiederholen; kein zweiter Kostenposten, keine erneute Ausführung. |
| Journal oder Quelle fällt aus | keine neue Zulassung; ThreadDesk-Notizen bleiben lokal nutzbar. Früher zugelassene Ergebnisse nicht als rückwirkend verhindert darstellen. |
| Alter Firmencontroller startet | RECOVERING/BLOCKED, bis unabhängiger aktueller Abgleich vorliegt; keine leere Bilanz, keine Rechte aus privatem Backup. |

## 10. Ereignisse und Migration

Der geplante Authority-Event-v2-Vertrag übernimmt den Herkunftsrahmen und ergänzt
explizit: `realm_id`, `source_journal_id`, `source_epoch`, `source_sequence`,
`company_ref`, `responsible_person_ref`, `acting_agent_ref`, `device_ref`,
`grant_ref`/Revision, `delegation_ref`, `call_id`, `reservation_ref`,
`admission_seq` bzw. `barrier_seq`, `accounting_ref` und eine datensparsame
`state`/`reason_code`-Kombination. Keine Anfrage-Payload oder öffentlichen
Inhaltsdigests. Betrachterrechte gelten auch für Personen-/Firmenreferenzen.

Neue Ereignisse sind `execution.intent`, `execution.reserved`,
`execution.admitted`, `execution.dispatch_attempted`,
`execution.provider_accepted`, `execution.outcome_unknown`,
`execution.cancelled_no_send`, `execution.settled` und `control.effective`.
Eigene v2-Validierung, Migration und Import erst in B7; v1 bleibt unverändert.
Unbekannte v2-Ereignisse dürfen nicht als v1-Allow importiert werden.

Zustandscommit und Outbox-Eintrag werden in derselben Quelltransaktion gespeichert.
Zustellung ist wiederholbar; Import identifiziert durch Quelle/Epoche/Ereignis-ID.
Gleiche ID mit anderem Inhalt ist ein Konflikt. Lücken werden nicht still
geschlossen. Pro Quelle geordnete Folgen sind keine automatisch globale Uhr.
Die endgültige Herkunftsabsicherung verwendet geprüfte Signaturen und unabhängig
verwahrte Kontrollstände nach eigener Spezifikation. Eine Hashkette allein
liefert keinen Schutz gegen einen Administrator, der alles ersetzt.

ThreadDesk-Anzeigenausfall verhindert keine bereits dauerhaft protokollierte
Ausführung. Ausfall des verpflichtenden Quellenjournals verhindert neue
Zulassungen. Der Import bleibt ohne Schreibzugriff auf fremde Produktdatenbanken.

## 11. Modellprüfung und Abschlussgrenze

[`check_execution_model.py`](check_execution_model.py) untersucht ein bewusst
kleines Zustandsmodell mit zwei Aufrufen, einem gemeinsamen Limit, asynchroner
Reservierung/Stornierung, Widerruf, Freeze, Quellenverlust und einem Crash.
Es prüft alle erreichbaren Zustände dieses Modells und muss absichtlich
eingebaute Protokollfehler erkennen. Der Bericht steht in
[`B0-VALIDATION.md`](B0-VALIDATION.md).

Das Modell ersetzt **nicht** kryptografische Prüfung, Datenbanktransaktionen,
reale Prozesse, Provider-Abrechnung, Browser-E2E oder die 22 Produkt-Abnahmefälle.
Gegenfälle für B4/B5 müssen später gegen echten Code laufen. Kein Zeitmodell,
keine Partitionstoleranz, kein Beweis für unbegrenzt viele Aufrufe.

| Modell-/Reviewgegenstand | Zuordnung zu GOLDENRULES |
| --- | --- |
| gemeinsame Reservierung und Hierarchie-Spezifikation | T05, T06, T16, T18 |
| Sperrbarriere vor/nach Zulassung und Folgeaufruf | T08, T09, T13 |
| einmalige IDs, Storno-Tombstone, Crash/unklarer Ausgang | T11, T12, T15 |
| Geräte-/Auftragsbindung und alte Rechte | T03, T04, T10, T14, T21 |
| feste Adapterziele und keine Schlüssel im Ereignis | T07, T19, T20, T22 |
| lokales Arbeiten und Inhaltssichtbarkeit | T01, T02, T17; außerhalb dieses Ausführungsmodells |

**B0-Ergebnis:** Zustands-/Fehlersemantik und Reihenfolge sind als Entwurf
konkretisiert. Vor B1/B3/B5 bleiben als ausdrückliche Review-Gates offen:
genehmigtes Identitäts-/Transportprofil mit Schlüsselaufnahme und Replay-Schutz;
4AllPass-ADR zum separaten Executor, selektiven Eintragszugriff und Recovery;
konkrete authentische Raumautorität; überprüfte Journal-/Signatur-/Checkpoint-
Spezifikation; ein Anbieteradapter mit belegbarer harter Kostenobergrenze.
Diese offenen Gates sind kein Auftrag, heute Kryptografie oder Produktcode zu
implementieren. B0 wird bis zum Review nicht als vollständig abgenommen geführt.

## 12. Primärquellen für verwendete Bausteine

- [RFC 9449](https://www.rfc-editor.org/rfc/rfc9449.html), insbesondere 4.3,
  7 und 11: DPoP-Prüfungen, Tokenbindung und Grenzen des Besitznachweises.
- [RFC 8785](https://www.rfc-editor.org/rfc/rfc8785.html), 3.1 und Anhang D:
  kanonisches JSON, doppelte Feldnamen und große Integer als Strings.
- Die Repositoryquellen in Abschnitt 1 und GOLDENRULES sind die Grundlage der
  Projektaufteilung. Der Koordinator-, Tombstone- und Budgetablauf ist unser
  Entwurf, keine von den RFCs zertifizierte Gesamtarchitektur.
