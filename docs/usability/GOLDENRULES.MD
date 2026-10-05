# GOLDENRULES.MD

Stand: 3. Oktober 2026. Verantwortliche Entscheidung: Kira, im Auftrag des Nutzers.

**Status: beschlossener Sicherheitsplan und vorbereiteter Bauauftrag. Die unten
beschriebenen neuen Sicherheitsmechanismen sind nicht implementiert oder als
Gesamtsystem nachgewiesen. Dieser Dokumentationsschritt startet keinen Bau.**

Diese Fassung hält die Entscheidungen zur Verbindung von ThreadDesk, 4AllPass
und TollGate fest. Der vereinbarte Pfad ist `docs/usability/GOLDENRULES.MD`.
Die früher erwähnte lokale Arbeitskopie war nicht verfügbar; auf dem geprüften
`main` und `feat/desktop-brand-icons` existierte diese Datei nicht. Ihr unbekannter
Wortlaut wird hier nicht als wiederhergestellt ausgegeben. Vor einer späteren
Zusammenführung sind zusätzliche ältere Regeln zu erhalten und Widersprüche
ausdrücklich aufzulösen. Keine konkurrierende `IMPLEMENTATION.md` anlegen.

## 1. Ziel und Entscheidung

Eine Person arbeitet allein sofort lokal. Mehrere eigene Geräte können später
ausdrücklich verbunden werden. Ein Team kann gemeinsame Inhalte bearbeiten und
firmenfinanzierte Dienste nutzen, ohne private Tresore anderer Menschen zu öffnen.

**Für kontrollierte Firmenaufrufe wird der dauerhafte Anbieterschlüssel nicht an
Mitarbeitergeräte oder Agenten ausgegeben.** Ein von der Firma kontrollierter
4AllPass-Ausführungsdienst benutzt ihn für einen konkret erlaubten Anbieteraufruf.
TollGate gibt dafür das Budget frei. ThreadDesk hält Auftrag und Ergebnis fest.

Dieser Ausführungsdienst ist ein optionales 4AllPass-Modul mit eigener
Vertrauensgrenze, kein vierter Produktkern und kein Umbau des verschlüsselten
Speicherservers. Er muss Geheimnisse für seine Aufgabe im Arbeitsspeicher
verarbeiten können. Der 4AllPass-CAS-/Sync-Server bleibt ein Speicher für
verschlüsselte Daten und erhält weder Tresorschlüssel noch Klartextgeheimnisse.

## 2. Geprüfter Ist-Stand

Die Aussagen in dieser Tabelle sind Codebefunde, keine neue Funktion.

| Produkt und geprüfter Commit | Vorhanden | Grenze für diesen Plan |
| --- | --- | --- |
| ThreadDesk `1de98700bbb6b14f32edde94a2fdabe7e3fa2338` | Räume, Rollen, lokale Gegenstellen, gemeinsame Whiteboard-Einträge, Konflikterhalt und lokale Gate-Regeln | `RoomBook` bindet Mitglieder heute an `instance_id`. HTTP-Sync ist auf Loopback/private IPv4-Adressen begrenzt. Das ist weder Personenidentität noch E2E-verschlüsselter Internet-Sync. |
| 4AllPass `47cc823d36f7731001a83f7fbda87d38ccc8e9b4` | Konten, mehrere Tresore pro Konto, `owner_user_id`, Geräte, Sitzungen, verschlüsselte Snapshots, lokaler Freigabe-Broker | Der laufende Broker liefert nach Allow `raw_secret`. `mediated` wird mit `handoff_unavailable` abgelehnt. Pairing-Token und Gerätekennung allein sind kein kryptografischer Agenten-/Gerätebeweis. |
| TollGate `d07c3ffb7513473a3de1c87bd01e9a1c9ea39c85` | Kostenprüfung, Consumer-Grenzen, Freeze, Ereignisse und atomare Reservierung einer Tagesaufrufzahl | `secrets.py` lädt Schlüssel aus `Key.txt`/Umgebung. `try_reserve_day_call` reserviert Aufrufzahlen, keinen gemeinsamen Geldhöchstbetrag. USD-Werte sind teilweise Schätzwerte. |

Die pauschale Aussage „TollGate hat heute keine API-Schlüssel“ ist damit falsch.
Für das neue kontrollierte Profil wird Schlüsselverarbeitung außerhalb von
TollGate verlangt; das ist eine Änderung am künftigen Ausführungsweg.

`4AllPass/docs/team-mode.md` vom 23. August ist weiterhin „Review only. Not
implemented.“ Dessen Phase 1 enthält ausdrücklich keinen Firmentresor.
**Gemeinsame Firmeneinträge und ihre Eintragsrechte bleiben Phase 2.** Ein
`organization_id` am privaten Tresor ersetzt keine dieser Voraussetzungen.

## 3. Zuständigkeiten und Begriffe

| Gegenstand | Zuständig | Bedeutung und Grenze |
| --- | --- | --- |
| Konto/Person | 4AllPass; ThreadDesk verknüpft seine Akteur-ID nach bestätigter Zuordnung | Anmeldung identifiziert ein Konto. Sie entschlüsselt keinen Tresor. Anzeigename, E-Mail-Text oder `actor_id` allein beweisen nichts. |
| Installation/Gerät | 4AllPass bestätigt den Gerätezugang; ThreadDesk behält `instance_id` | Person und Installation bleiben verschieden. Kopieren eines Arbeitsordners erzeugt kein zugelassenes Gerät. |
| Firma | 4AllPass-Firmenmodell, Phase 2 | Verwaltung, eigenes Eigentum, getrennte Wiederherstellung. Keine automatische Macht über private Mitarbeitertresore. |
| Team/Raum | ThreadDesk | Gemeinsame Inhalte und Rollen. Mitgliedschaft erzeugt weder Tresorrechte noch Geld. |
| Tresor/Eintrag | 4AllPass | Mehrere Tresore je Eigentümer möglich. Eine Firma kann mehrere Tresore haben. Ein Team braucht keinen eigenen Tresor. |
| Persönliche Eintragsfreigabe | 4AllPass | Eine Person darf einen bestimmten Eintrag für festgelegte Operationen und Bedingungen benutzen. |
| Gemeinsame Budgetgrenze | TollGate | Ein Budget kann viele persönliche Freigaben, Geräte und Agenten umfassen. |
| Agentenauftrag | Verantwortliche Person innerhalb ihrer 4AllPass-Freigabe | Erlaubt einen begrenzten Auftrag; erzeugt keine höheren Rechte. |
| Projektstand/Ergebnis | ThreadDesk | Speichert Kontext und überprüfbare Verweise. Ein importierter Eintrag ist keine Ausführungserlaubnis. |

4AllPass bleibt die Schnittstelle für Identität, Geheimnisse und Freigaben.
TollGate entscheidet über Geld und Sperren. ThreadDesk entscheidet über seine
Rauminhalte. Kein Programm schreibt unmittelbar in die Datenbank eines anderen.
Die lokale KI bleibt im bestehenden Modulrahmen; dieser Plan erweitert
ihre Rechte nicht. Externe Agentenausführung bleibt außerhalb des ThreadDesk-Kerns.

## 4. Allein, eigene Geräte, Team und Sync

| Nutzung | Verbindliches Ziel |
| --- | --- |
| Eine Person, ein Gerät | ThreadDesk startet lokal ohne Pflichtkonto, Firma oder Team. Lokale Arbeit und vorhandene lokale KI brauchen keine Firmeninfrastruktur. |
| Eine Person, mehrere Geräte | Optionaler persönlicher Sync nach bestätigter 4AllPass-Kontozuordnung und gesonderter Zulassung jedes Geräts. Keine künstliche Firma und keine Teameinladungen nötig. |
| Mehrere Personen | Gesonderte Raumaufnahme, Rollen und nachprüfbare Geräte-/Personenzuordnung. Geheimnisfreigaben erfolgen zusätzlich in 4AllPass. |
| Bezahlte Firmenaufrufe | Gemeinsame aktuelle Rechte- und Budgetprüfung am firmeneigenen Ausführungsweg. Kein Offline-Kontingent in der ersten kontrollierten Ausgabe. |

Sichtbarkeit ist ausdrücklich `nur lokal`, `eigene Geräte` oder `Raum`.
Bestehende private Notizen/Einträge bleiben **nur lokal**, bis die Person eine
gesonderte Freigabe erteilt. Ein Login oder eine Raumaufnahme ändert das nicht.
Die heute vorhandenen Felder sind damit nicht automatisch migriert.

Persönlicher und Team-Sync übertragen freigegebene Inhalte verschlüsselt zwischen
zugelassenen Endgeräten. Transportverschlüsselung und E2E-Verschlüsselung sind
getrennte Anforderungen. Raumschlüssel sind keine Tresorschlüssel. Ein reiner
Relay-/Speicherbetreiber erhält keine Inhaltsschlüssel. Kein öffentlicher Zugriff
auf die heutige lokale HTTP-Oberfläche; Internet-Sync benötigt einen eigenen,
geprüften Transport. Ein Konto bestätigt die Zuordnung, nicht automatisch alle
Entschlüsselungsrechte.

Whiteboard-Einträge bleiben append-only. Ein stabiler Eintragsschlüssel verhindert
Doppelungen; gleiche ID mit verschiedenem Inhalt ist ein sichtbarer Konflikt.
Geräteuhren beweisen keine globale Reihenfolge. Offline-Arbeit bleibt lokal;
Wiederverbindung prüft aktuelle Mitgliedschaft und Schreibrechte **vor** Übernahme.
Nicht mehr zulässige Offline-Beiträge bleiben als lokale Entwürfe erhalten.

Entfernte Geräte/Mitglieder erhalten keine neuen Raumschlüssel und keine neuen
Daten. Bereits gelesene oder kopierte Inhalte können nicht zurückgerufen werden.
Ein gelöschter Peer oder ein neues Gerät darf seine alten Rechte nicht aus einem
Backup wiederherstellen. Mitgliedschaftsänderungen benötigen einen aktuellen,
authentischen Versionsstand; alte Sync-Bündel dürfen sie nicht überschreiben.

Smartphone/Passkey können ein Zugangsmittel sein. Smartphone, Telefonnummer oder
Personalausweisnummer werden weder zur Pflicht noch zum geheimen Hauptschlüssel.
Die Zuordnung belegt das zugelassene Konto/Gerät, keine staatlich geprüfte Identität.

## 5. Ein maßgeblicher Firmeneintrag, getrennte Rechte

Ein Anbieterschlüssel hat einen maßgeblichen Eintrag im Firmentresor. Freigaben
für Anna und Ben oder zwei Teams verweisen auf denselben Eintrag. Verschlüsselte
Backups und kurzzeitige Verarbeitung sind keine zusätzlichen fachlichen Tresore.

Rechte werden getrennt geprüft: **benutzen**, **Freigaben verwalten**,
**Schlüssel verwalten/ersetzen** und gegebenenfalls **Geheimnis ansehen/exportieren**.
Benutzen gewährt keines der anderen Rechte. Eine ThreadDesk-Leitungsrolle gewährt
keines davon. Verwaltung einer Freigabe setzt ausdrückliche 4AllPass-Berechtigung
für den betroffenen Firmeneintrag voraus.

Eintragsfreigaben geben keinen gesamten Firmentresorschlüssel heraus. Der
Ausführungsdienst erhält nur die für seine freigegebenen Einträge erforderliche
kryptografische Fähigkeit. Ein selektives Schlüsselschema ist vor Umsetzung
gesondert in 4AllPass zu spezifizieren und zu prüfen. Keine neue Kryptografie im
ThreadDesk-Kern und keine Umdeutung der bestehenden Ganz-Tresor-Geräte-Envelopes.

Eine Freigabe enthält mindestens Eigentümer/Firma, Person, zugelassene Geräte,
Eintrag, erlaubte Operationen/Anbieter, Zweck-/Raumbindung soweit erforderlich,
gemeinsame `budget_id`, Laufzeit, Agentennutzung ja/nein, Status und Revision.
Die Werte kommen aus der überprüften Freigabe, nicht aus behaupteten Client-Feldern.
Ein freier Zwecktext bleibt eine Beschreibung; technische Grenzen müssen in
prüfbare Operationen, Ziele und Parameter übersetzt werden.

Firmenfreigaben hängen immer an aktiver Firmenmitgliedschaft; raumgebundene
Freigaben zusätzlich an aktiver Raumzugehörigkeit. Freigabe ist eine notwendige
zusätzliche Bedingung. Die Schnittmenge wird bei jedem Aufruf geprüft.

## 6. Kontrollierter Ausführungsweg

1. Eine Person beauftragt einen Agenten oder fordert selbst einen konkreten
   Anbieteraufruf an. Der Auftrag referenziert die bestehende Freigabe.
2. Der 4AllPass-Ausführungsdienst prüft Person, Gerätebesitznachweis, handelnden
   Agenten, aktuelle Freigabe, Mitgliedschaft, Auftrag und erlaubte Operation.
3. Er bestimmt aus dem tatsächlich auszuführenden Aufruf eine belastbare
   Kostenobergrenze. TollGate reserviert sie verbindlich im gemeinsamen Budget.
4. Vor Versand werden aktuelle Rechte/Sperren erneut geprüft, Auftrag und
   Reservierung unveränderlich aneinander gebunden und die einmalige
   Versandfreigabe verbraucht. Ein dauerhafter Versandnachweis entsteht.
5. Nur dieser Dienst setzt das Geheimnis ein und spricht den freigegebenen
   Anbieter an. Person/Agent erhalten das geprüfte Ergebnis, keinen Schlüssel.
6. TollGate verbucht belegte Kosten; die Quelle liefert sekretfreie Ereignisse.
   ThreadDesk kann diese über den Ereignisvertrag importieren.

Der Dienst läuft für Firmen auf einem Rechner, den Mitarbeiter und ihre Agenten
nicht administrieren. 4AllPass-Modul und TollGate können für die erste Ausgabe
auf demselben Firmenhost betrieben werden, mit getrennten Prozessrechten. Kein
Pflicht-Cloudanbieter. Bei privater Nutzung kann der Besitzer beide lokal
betreiben; gegen den Besitzer mit Administratorrechten wird keine unüberwindbare
Budgetgrenze behauptet.

Der Klartext ist im Ausführungsdienst unvermeidbar. Dessen Betreiber, Programmcode
und Betriebssystem gehören zur Vertrauensbasis. Der Dienst sieht außerdem die
Inhalte der dort ausgeführten Anbieteraufrufe; private, nicht übergebene Threads
sieht er nicht. „Zero-Knowledge“ gilt für den verschlüsselten Speicher, nicht für
diesen ausführenden Prozess. Betriebliches Reporting zeigt keine Geheimnisse;
berechtigte Schlüsselverwalter werden nicht als technisch schlüsselblind ausgegeben.

**Kein Umgehungsweg:** kontrollierte Firmeneinträge sind von `raw_secret`, Export
an Mitarbeiter, Umgebungsdateien, altem Pairing und Direktaufrufen ausgeschlossen.
Bereits verteilte Schlüssel müssen vor Aktivierung dieses Profils beim Anbieter
ersetzt/widerrufen werden. Sonst bleibt die behauptete Durchsetzung unmöglich.
Eine Ablehnung von 4AllPass oder TollGate beendet den Versuch; kein stiller
Fallback auf einen Dateischlüssel, anderen Anbieter oder andere Budget-ID.

Der Executor ist kein allgemeiner HTTP-Proxy: feste freigegebene Anbieterziele,
Methoden, Modelle und Parameterschemata; keine vom Agenten gewählten Auth-Header,
Weiterleitungen oder internen Netzadressen. TLS-Prüfung ist zwingend. Antwort-
und Fehlerformate dürfen keine Schlüssel/Header zurückreichen. Unvertrauenswürdige
Modellantworten und Raumbeiträge erzeugen keine neuen Rechte.

## 7. Agentenauftrag und Identität

Eine Beauftragung bindet Person, Agent, zugelassenes Gerät, Freigabe/Revision,
Eintrag, Auftrag/Lauf, erlaubte Aktionen, Frist und Budget zusammen. Sie darf die
Firmenfreigabe nur einschränken. Weitere Agenten oder Folgeaufträge benötigen eine
ausdrücklich erlaubte, ebenso begrenzte Delegation; zunächst keine Unterdelegation.

Ein vom gleichen Menschen betriebener zweiter Agent ist keine automatisch
berechtigte Kopie. Mensch und handelnder Agent bleiben im Nachweis getrennt.
Die Verbindung von Account, `actor_id` und `instance_id` wird nach bestätigter
Anmeldung und Geräteaufnahme festgehalten. Geräte/Agenten weisen den Besitz ihrer
zugelassenen Schlüssel am Aufruf nach. Client-IDs, Bearer-Token plus kopierte
Gerätekennung und bloße Prozessnamen reichen für das Firmenprofil nicht aus.
Ein Hardware- oder Integritätsnachweis für ein schadsoftwarefreies Gerät folgt
daraus ausdrücklich nicht.

Die Aufnahme eines weiteren Firmengeräts benötigt eine bereits vertrauenswürdige
Bestätigung oder den festgelegten Firmen-Recovery-Weg. Ein gestohlenes
Kontopasswort darf nicht allein ein neues Firmengerät zulassen. Interne
Dienstverbindungen sind authentisiert und auf die fest konfigurierte Gegenstelle
gebunden; ein vom Client benannter anderer Executor oder TollGate ist kein Ersatz.
Maßgeblich für raumgebundene Firmenrechte ist der bestätigte Mitgliedschaftsstand
der zuständigen Raumverwaltung, niemals eine lokal editierbare `rooms.json`.

Ein Auftrag wird über eine feste Kennung und seine geprüften Parameter gebunden;
jeder Ausführungsversuch zusätzlich an einen Digest der konkreten Anfrage.
Dies verhindert Austausch nach Budget-/Rechteprüfung. Es beweist nicht, dass ein
erlaubter Prompt inhaltlich dem geschäftlichen Zweck dient. Weitergehende
fachliche Beschränkungen brauchen eigene prüfbare Regeln.

Ein geteilter Whiteboard-Eintrag oder eine Modellantwort kann einen Vorschlag
enthalten. Beides darf weder eine persönliche Beauftragung noch einen Allow-
Entscheid oder eine Budgeterhöhung ersetzen.

## 8. Gemeinsames Budget und Kostenobergrenze

Die Budgetgrenze kommt von einem dazu berechtigten Firmenverwalter. Ihre
Erstellung/Änderung ist authentisiert und versioniert. ThreadDesk, Agenten und
ein einfacher Empfänger einer Eintragsfreigabe dürfen sie nicht erhöhen.

Für alle Aufrufe derselben Budgetperiode gilt atomar:

**Verbraucht + offene Reservierungen + neuer Höchstbetrag ≤ genehmigte Grenze.**

100 Dollar für ein Team sind 100 Dollar zusammen. Zusätzliche Personen, Geräte,
Freigaben, Neustarts und Verlängerungen verdoppeln diese Grenze nicht.
Übergeordnete Firmen-/Projektgrenzen und untergeordnete Laufgrenzen werden bei
einer Reservierung gemeinsam berücksichtigt, nicht nacheinander überschritten.

Die erste Ausgabe verwendet genau eine verbindliche TollGate-Budgetstelle pro
Budget mit dauerhaftem, transaktionalem Journal. Kein verteilter Offline-Zähler,
kein automatischer Wechsel zu einer leeren Zweitinstanz. Reservierungen aller
relevanten Grenzen erfolgen in einer Transaktion. Geld wird als ganzzahliger
Betrag einer festen Untereinheit und Währung geführt; keine Gleitkomma-Bilanz.

Ein Aufruf wird nur zugelassen, wenn der geprüfte Anbieteradapter einen echten
Höchstbetrag für **alle** abrechenbaren Bestandteile festlegen kann: Eingabe,
maximale Ausgabe, weitere Tokens/Tools, feste Gebühren und mögliche Versuche.
Preistabelle und Begrenzungen werden versioniert. Eine grobe Tokenschätzung oder
ein vom Agenten behaupteter Preis reicht nicht. Nicht begrenzbare Operationen
werden im harten Firmenprofil abgelehnt. Ein aufgeladener Anbietersaldo erhöht
die Firmengrenze nie; ein Anbieterlimit zählt nur, soweit es tatsächlich hart ist.

Eine Budgetperiode hat eine feste, vom Verwalter festgelegte Grenze und Zeitbasis.
Tageswechsel wird aus der Uhr der Budgetstelle berechnet, nicht aus Geräteuhren.
Alte Reservierungen bleiben ihrer Periode zugeordnet; sie verschwinden nicht beim
Wechsel. Bei Gesamtausgabenlimits gilt die zusätzliche periodenübergreifende
Grenze. Wesentliche Unsicherheit über Zeit, Preis oder Abrechnung sperrt neue
betroffene Aufrufe. Eine Senkung unter bestehende Verpflichtungen erzeugt keine
Rückbuchung: neue Aufrufe bleiben gesperrt.

Die harte Zusage gilt für zugelassene, technisch begrenzbare Aufrufe über diesen
Weg und eine korrekte Anbieterabrechnung. Kosten durch andere Schlüssel, einen
kompromittierten Firmenhost oder abweichende Anbieterabrechnung liegen außerhalb
dieser Garantie und werden nicht als kontrolliert ausgegeben.

## 9. Abbrüche, Wiederholung, Freeze und Widerruf

Jeder Versuch hat eine eindeutige Aufruf-ID und eine daran gebundene Reservierung.
Person, Gerät, Agent, Eintrag, Anbieter, Anfrage-Digest, Budget und Richtlinien-
Revision dürfen während des Versuchs nicht ausgetauscht werden. Eine Wiederholung
mit derselben ID und anderen Parametern wird abgelehnt.

| Zustand | Verbindliches Verhalten |
| --- | --- |
| Vor Versand abgelehnt | Kein Anbieteraufruf. Reservierung nur freigeben, wenn der Nichtversand dauerhaft nachgewiesen ist. |
| Zum Versand freigegeben/gesendet | Reservierung bleibt bis zur belastbaren Abrechnung gebunden. |
| Erfolg oder berechneter Fehler | Tatsächliche belegte Kosten genau einmal abrechnen; erst dann unbenötigten Rest freigeben. |
| Timeout/Crash/Verbindungsabbruch, Ausgang unklar | Kein blindes Wiederholen und keine Freigabe per Ablaufzeit. Höchstbetrag bleibt gebunden oder konservativ verbucht; Status „Ausgang/Kosten unklar“. |
| Wiederholung | Nur bei belegtem Nichtversand oder nachgewiesener Anbieter-Idempotenz automatisch. Sonst eigener bewusst zugelassener Versuch mit zusätzlicher Reservierung. |
| Streaming/Tool-Folge | Streaming ist kein Freibrief. Jeder weitere bezahlte Anbieteraufruf durchläuft die ganze Prüfung; ein einzelner Aufruf ist durch seine Parameter vorab begrenzt. |

„Genau einmal“ wird nicht für externe Anbieterwirkung versprochen. Reservierung,
Versandjournal und Abrechnung müssen gegen Wiederholung idempotent sein; bei
unklarem externem Ergebnis wird angehalten.

Die erste kontrollierte Ausgabe verwendet **einen aktiven Versandkoordinator
innerhalb des 4AllPass-Executors**. Er ordnet Versandzulassung, Freigabewiderruf,
Mitgliedschaftsentzug und Freeze in einem dauerhaften Befehlsjournal. Das ist
Koordination der vorhandenen Zuständigkeiten, keine Budgetentscheidung in 4AllPass.
4AllPass prüft Rechte, TollGate die Geld-/Sperrentscheidung. Keiner ersetzt die
Entscheidung des anderen aus einem Cache.

Unter derselben kurzen Serialisierung pro Ausführungsbereich: aktuellen
Rechtezustand prüfen, bei TollGate atomar reservieren und aktuell gesperrte
Budgets ausschließen, den unveränderlichen Versanddatensatz dauerhaft schreiben,
danach genau diesen Versuch endgültig zum Versand zulassen. Alle internen
Nachrichten tragen dieselbe Aufruf-ID; wiederholte Nachrichten ändern das Ergebnis
nicht. Reißt eine Verbindung in dieser Folge ab, wird nicht versandt bzw. ein
bereits zugelassener Versuch als unklar behandelt. Finanzielle Verpflichtungen
werden dabei nicht optimistisch zurückgebucht.

Alle Wege für wirksamen Firmen-Widerruf und Freeze, auch automatische Sperren,
müssen dieselbe Reihenfolge durchlaufen. Quellen dürfen einen Entzug bereits
vormerken; „wirksam bestätigt“ wird er erst nach dem dauerhaften Sperreintrag des
aktiven Koordinators. Eine neue Version invalidiert alle noch nicht endgültig
zugelassenen Versuche. Können Koordinator oder aktuelle Quellstände nicht geprüft
werden, erfolgt keine neue Zulassung. Es gibt keine vom Koordinator unabhängige
Weiterverwendung vorbereiteter Versandfreigaben.

Ein Neustart stellt zuerst Sperren, letzte Revisionen und offene Versuche wieder
her. Unklare endgültig zugelassene Versuche werden nicht automatisch erneut
gesendet. Kein automatisches Failover und keine zwei aktiven Koordinatoren in
dieser Ausgabe. Die Zustandsmaschine und der serialisierte Ablauf sind in B0 als
Protokoll zu konkretisieren und insbesondere durch T08/T12/T13/T15 zu beweisen.

**Ein bestätigter Widerruf verhindert alle danach zugelassenen Anbieteraufrufe.**
Ein vor ihm endgültig zugelassener Aufruf zählt als in Bearbeitung und kann noch
Kosten erzeugen; enge Versandfrist, keine später wiederverwendbare Freigabe.
Widerruf vor endgültiger Versandzulassung stoppt auch bereits vorbereitete
Aufrufe. Bestätigung eines Widerrufs darf erst erfolgen, wenn diese Reihenfolge
an der aktiven Ausführungsstelle wirksam ist. Kein Sofortstoppversprechen für einen
bereits beim Anbieter angenommenen Auftrag.

Bei Unerreichbarkeit von Rechteprüfung, Budgetstelle oder verpflichtendem
Versandjournal gibt es keine neue Versandzulassung. Lokale ThreadDesk-Arbeit
bleibt möglich. Die Sperre gilt auch nach Neustart und bei beschädigtem Journal.

## 10. Austritt und Wiederherstellung

Firmenaustritt sperrt Firmenmitgliedschaft, zugehörige Freigaben und neue
Versandzulassungen. Raum-Austritt sperrt raumgebundene Freigaben und Raumsync.
Beide Vorgänge sind verschieden. Eine bereits entfernte Person erhält durch
einen alten Raumstand oder einen erneuten Einladungstext keine Firmenrechte.

Private Wiederherstellung stellt private Daten wieder her. Ein neues oder
wiederhergestelltes Gerät wird für Firmenzugriff erneut aufgenommen; es übernimmt
keine Firmenbeauftragung oder alte Sitzung automatisch. Betriebsschlüssel,
Firmenfreigaben und deren Aktualität werden nicht aus einem privaten ThreadDesk-
Backup autorisiert. Das verhindert künftige Firmenaufrufe, löscht aber keine
früher empfangenen Klartexte.

Firmeneigentum erhält einen eigenen Wiederherstellungsweg, unabhängig vom
privaten Konto einer einzelnen Leitung. Für die erste Firmenausgabe wird eine
gesonderte Firmen-Recovery mit zwei getrennt verwahrten Anteilen vorgesehen;
Zusammenführen ausschließlich im vertrauenswürdigen Wiederherstellungsclient.
Keine Server-Verwahrung des vollständigen Wiederherstellungsschlüssels und kein
Zugriff auf private Mitarbeitertresore. Das konkrete Verfahren muss den bereits
vorgesehenen 4AllPass-Recovery-Ansatz nach gesonderter Spezifikation verwenden.
Zwei Personen als Verwahrer bieten organisatorische Trennung; bei nur einer
Person mit zwei getrennten Aufbewahrungsorten wird diese Trennung nicht behauptet.
Der Verlust eines erforderlichen Anteils bleibt ein Verfügbarkeitsrisiko.

Nach Wiederherstellung eines Firmencontrollers bleiben bezahlte Aufrufe zunächst
gesperrt. Aktueller Mitgliedschafts-/Widerrufsstand, Geräteaufnahme und Kostenjournal
werden mit unabhängigen aktuellen Kontrollständen und Anbieterbelegen abgeglichen.
Ungeklärte Aufrufe bleiben finanziell gebunden. Ein Backup ist kein Beweis, dass
sein Stand noch aktuell ist. Ist der aktuelle Stand nicht belegbar, bleiben die
betroffenen alten Rechte gesperrt; neue Geräte-/Freigabegeneration erfordert eine
bewusste Firmenentscheidung. Ein altes Budget darf niemals auf null zurückgesetzt
und unbemerkt erneut ausgegeben werden.

Beim Ersatz eines verlorenen oder möglicherweise kopierten Executors wird der
alte Dienstzugang gesperrt und der betroffene Anbieterschlüssel rotiert, bevor
der neue Executor bezahlte Aufrufe übernimmt. Ein neu benannter Controller allein
macht einen alten Klartextschlüssel nicht ungültig. Die alte Kopie darf nicht
parallel mit demselben Budget weiterarbeiten.

## 11. Nachweise ohne Geheimnisse

Ein Freigabeereignis beweist eine Entscheidung, kein ausgeführtes Geschäft.
Ein Versandnachweis beweist den Versandversuch, keine Anbieterannahme. Erfasst
werden getrennt: abgelehnt, reserviert, zum Versand zugelassen, angenommen soweit
belegt, abgeschlossen/fehlgeschlagen und Ausgang/Kosten unklar.

Mindestens verknüpft: Firma, verantwortliche Person, handelnder Agent, Gerät,
Freigabe/Revision, Eintrag als unkritische Referenz, Auftrag/Lauf, Aufruf-ID,
Budget/Reservierung, Zeitpunkt, Entscheidung, Anbieter-Nachweis soweit vorhanden
und Abrechnung. Keine API-Schlüssel, Autorisierungsheader, Passwörter, Prompts
oder privaten Thread-Inhalte in diesen Ereignissen. Sensible Referenzen bleiben
auf berechtigte Betrachter begrenzt; keine öffentlichen Personenprofile.

Das vorhandene Authority-Event-v1-Schema hat feste Felder und Ereignistypen.
Neue Angaben/Zustände brauchen eine ausdrücklich versionierte Erweiterung samt
Validator, Migration und producer-spezifischer Zuordnung. Sie werden nicht still
in v1 hineingeschrieben. TollGate schreibt weiterhin nicht in ThreadDesk.
Die Firma benötigt Zugriff auf das maßgebliche Journal auch dann, wenn ein
Mitarbeiter seine lokale ThreadDesk-Anzeige löscht.

Die Quelle hält ein dauerhaftes, geordnetes Journal und wiederholbar zustellbare
Ereignisse. ThreadDesk importiert idempotent. Ein Ausfall der Anzeige muss keine
bereits dauerhaft protokollierte Ausführung verhindern; ein Ausfall des
verpflichtenden Quellenjournals verhindert dagegen neue Versandzulassungen.
Einfache Hashketten beweisen weder Urheber noch Vollständigkeit gegenüber einem
Administrator, der die ganze Datei ersetzen kann. Herkunftsschutz und getrennte
Kontrollstände sind im Protokoll festzulegen; keine unbelegte Audit-Garantie.

## 12. Baufolge und Abschlussbedingungen

Die Produktentscheidung ist getroffen. Vor Produktcode fehlen noch konkrete
Protokollnachweise; diese Tabelle ist der vorbereitete Bauauftrag, keine
Behauptung, dass die Mechanismen bereits laufen. Keine Phase überspringen.

| Schritt | Zuständig / Auftrag | Abschlussbedingung |
| --- | --- | --- |
| B0: Verträge | Bestehende Verträge lesen; versionierte Daten-/Fehlerzustände für Gerätebeweis, Freigabe, Auftrag, Budgetreservierung, Widerruf und Versandjournal spezifizieren. | Ein konkretes Sequenzmodell einschließlich Crash-/Race-Fällen; keine offene Bedeutung von „Widerruf bestätigt“ oder „versandt“. |
| B1: Lokale Nutzung und Identitätszuordnung | Vorhandene ThreadDesk-IDs erhalten; bestätigte 4AllPass-Person-/Gerätebindung ergänzen. | Lokal ohne Pflichtkonto; kopierter Ordner, vertauschte Person und gestohlene Kennung reichen nicht zur Firmenanmeldung. |
| B2: Persönlicher/Team-Sync | Vorhandenen Merge wiederverwenden; Sichtbarkeit, authentische Mitgliedschaft, Rechteänderungen und verschlüsselten Transport spezifizieren/umsetzen. | Zwei echte Prozesse/Geräte; Offline, Neustart, Austritt, Read-only und Konflikte funktionieren, private lokale Inhalte verlassen das Gerät nicht. |
| B3: Firmentresor, Phase 2 | In 4AllPass Organisationseigentum, getrennte Eintragsrechte, selektive Verschlüsselung und Firmen-Recovery nach eigenem Architekturreview umsetzen. | Empfänger kann erlaubten Eintrag benutzen, keine Nachbareinträge/private Tresore öffnen und keine Freigaben weiterreichen. |
| B4: Gemeinsames Geldjournal | In TollGate atomare Geldreservierung mit Höchstbeträgen, Perioden, Hierarchie, Wiederholungsschutz und Wiederanlauf ergänzen. | Gleichzeitige Geräte können das gemeinsame Limit nicht überschreiten; unbekannte Abrechnung schafft kein neues Budget. |
| B5: Vermittelte Ausführung | Separates 4AllPass-Executor-Modul an B0/B3/B4 anbinden; zunächst ein synthetischer Anbieter mit festen Kosten. | Ablehnung verhindert nachweislich jeden Anbieteraufruf; kein Schlüssel erreicht Mitarbeiter/Agent/TollGate; kein Legacy-Fallback. |
| B6: Ein realer Anbieter | Genau eine begrenzbare Operation anbinden; dokumentierte Preis-/Höchstbetragsgrundlage prüfen, Freigaben und Adaptertests vervollständigen. | Kostenobergrenze belegbar, Schlüsselrotation beim Wechsel ins kontrollierte Profil nachgewiesen; keine Freischaltung bei fehlendem Beweis. |
| B7: Ereignisse und Bedienung | Versionierten Quellenjournal-Export und ThreadDesk-Import anbinden. Oberflächen DE/EN mit konkreten Zuständen. | Person/Agent und geplant/tatsächlich/unklar getrennt; keine Geheimnisse; keine Rechte durch Import. |
| B8: Gesamtabnahme | Gesamtkette mit synthetischen Nutzern und temporären Arbeitsbereichen adversarial testen. | Alle Fälle aus Abschnitt 13 bestanden, geprüfter Commit und Belege gespeichert; reale Kosten nur bei ausdrücklich dafür freigegebenem Test. |

4AllPass führt Protokoll-/Kryptoänderungen nach seinen Repository-Regeln durch:
erst Architekturentscheidung, dann kleiner Branch/PR, passende Spezifikation und
Tests. Diese Datei ist der zentrale produktübergreifende Beschluss; notwendige
technische Spezifikationen ersetzen sie nicht und dürfen sie nicht still ändern.
Keine neue Implementierung aus diesem Dokumentations-PR heraus starten.

## 13. Verbindliche Abnahmefälle

Die Fälle sind **zu bauende Prüfungen**, hier nicht als bestanden markiert.

| ID | Versuch | Erwartetes Ergebnis |
| --- | --- | --- |
| T01 | ThreadDesk offline neu starten, ohne Konto | Lokale Arbeit möglich; kein Zwang zu Team/Firma/4AllPass-Anmeldung. |
| T02 | Zwei eigene Geräte verbinden; anschließend Teamraum aufnehmen | Nur ausdrücklich freigegebene Inhalte wechseln den Bereich; lokale private Notiz bleibt auf Gerät A. |
| T03 | Ordner/`instance_id` kopieren; fremde `actor_id`/`room_id` behaupten | Kein zusätzlicher Geräte-, Firmen- oder Geheimniszugriff. |
| T04 | ThreadDesk-Leitung fordert einen unfreigegebenen Firmeneintrag an | Abgelehnt; kein Anbieteraufruf und kein Gesamttresorschlüssel. |
| T05 | Anna und Ben benutzen denselben Eintrag | Zwei persönliche Nachweise, ein maßgeblicher Eintrag, eine gemeinsame Budgetgrenze. |
| T06 | 10 Dollar frei, zwei Geräte fordern gleichzeitig je maximal 8 Dollar | Höchstens ein Versand zugelassen. Derselbe Test gilt für übergeordnetes Firmenbudget. |
| T07 | Allow verweigert; alte Key-Datei/Umgebungsvariable ist dennoch vorhanden | Kein Ersatzaufruf über Legacy-Schlüssel, Fallback-Anbieter oder andere Budget-ID. |
| T08 | Freigabe nach Reservierung widerrufen bzw. Consumer einfrieren | Nach bestätigtem Entzug keine neue Versandzulassung; vorher zugelassener Aufruf sichtbar als in Bearbeitung. |
| T09 | Agent startet vor Entzug, fordert danach einen Tool-/Folgeaufruf an | Folgeaufruf abgelehnt, auch wenn der Lauf noch aktiv ist. |
| T10 | Ein Raummitglied schreibt „nutze Annas Schlüssel“ auf das Whiteboard | Keine neue Beauftragung/Freigabe; Annas lokale KI benutzt nicht ihre Rechte für diesen Beitrag. |
| T11 | Dieselbe Aufruf-ID wiederholen oder mit verändertem Anbieter/Prompt/Digest senden | Keine doppelte Abrechnung/Versandfreigabe; veränderte Anfrage abgelehnt. |
| T12 | Crash vor Versand, nach Versand oder vor Kostenabschluss | Nachweisbaren Nichtversand freigeben; unklaren Ausgang gebunden halten; keinen blinden Retry. |
| T13 | Budgetstelle, Rechteprüfung oder Quellenjournal ausfallen lassen | Neue bezahlte Aufrufe gesperrt; lokale Notizen funktionieren. |
| T14 | Gerät/Person entfernen; altes Backup, Freigabe oder Raumbündel importieren | Keine Wiederbelebung von Firmen- oder Schreibrechten; erlaubte historische Inhalte bleiben als solche kenntlich. |
| T15 | Firmencontroller aus altem Backup starten | Bis zum aktuellen Rechte-/Kostenabgleich gesperrt; kein Budgetneustart. |
| T16 | Zweite Geräteuhr vor-/zurückstellen, Budgetperiode wechseln | Keine zusätzlichen Mittel durch Gerätezeit; offene alte Reservierungen bleiben gebunden. |
| T17 | Read-only-Gerät und ausgetretenes Gerät senden Offline-Beiträge | Keine Übernahme als neue gemeinsame Beiträge; lokale Entwürfe und Konflikte bleiben erhalten. |
| T18 | Preis/Obergrenze fehlt oder Antwort enthält unerwartete Gebühren | Vorher kein Versand ohne belastbare Grenze; Abweichung erzeugt Sperre/Incident statt stiller Budgetfreigabe. |
| T19 | Agent fordert fremde URL, Redirect, Auth-Header oder interne Adresse | Kein solcher Netzwerkaufruf und keine Geheimnisweitergabe. |
| T20 | Ereignisse duplizieren, verändern, auslassen oder ThreadDesk-Anzeige löschen | Duplikate idempotent; ungültige Herkunft abgelehnt; nachweisbare Lücken sichtbar; Firmenjournal bleibt maßgeblich. |
| T21 | Eintragsnutzer fordert Export, Nachbareintrag oder Weiterfreigabe | Abgelehnt; Nutzung erteilt keine zusätzliche Verwaltungsmacht. |
| T22 | Synthetischen Schlüssel in Fehlern, Streams, Logs und Ergebnissen suchen | Kein Schlüssel in Mitarbeiter-/Agentenantwort, TollGate-Zustand oder Ereignissen. |

Das Ergebnis der Planung lautet: **Architekturentscheidungen getroffen; heutige
Firmen-Sicherheitszusage gesperrt, bis die erforderlichen Mechanismen und Tests
vorliegen.** Bestehende lokale Funktionen bleiben nutzbar. Eine grüne alte
Testsuite ist kein Nachweis für die neue Gesamtkette.

## 14. Nachweise und fachliche Grundlage

Codeprüfung am 3. Oktober 2026, auf die in Abschnitt 2 genannten Commits fixiert:

- [ThreadDesk Raum-Sync](https://github.com/landjunge/threaddesk/blob/1de98700bbb6b14f32edde94a2fdabe7e3fa2338/src/threaddesk/services/room_sync.py), [Abschlussplan](https://github.com/landjunge/threaddesk/blob/1de98700bbb6b14f32edde94a2fdabe7e3fa2338/docs/TEAMPLAN.md), [Authority-v1-Schema](https://github.com/landjunge/threaddesk/blob/1de98700bbb6b14f32edde94a2fdabe7e3fa2338/docs/authority/authority-event-v1.schema.json).
- [4AllPass Sicherheitsgrenze](https://github.com/landjunge/4AllPass/blob/47cc823d36f7731001a83f7fbda87d38ccc8e9b4/docs/security-boundary.md), [Team-Entwurf](https://github.com/landjunge/4AllPass/blob/47cc823d36f7731001a83f7fbda87d38ccc8e9b4/docs/team-mode.md), [Vault-Modell](https://github.com/landjunge/4AllPass/blob/47cc823d36f7731001a83f7fbda87d38ccc8e9b4/backend/app/models/vault.py), [Handoff-Verfügbarkeit](https://github.com/landjunge/4AllPass/blob/47cc823d36f7731001a83f7fbda87d38ccc8e9b4/packages/core/src/access/handoff.ts).
- [TollGate Schlüsselquellen](https://github.com/landjunge/tollgate/blob/d07c3ffb7513473a3de1c87bd01e9a1c9ea39c85/src/tollgate/secrets.py), [Usage-Ledger](https://github.com/landjunge/tollgate/blob/d07c3ffb7513473a3de1c87bd01e9a1c9ea39c85/src/tollgate/usage_ledger.py), [Kostenschätzung](https://github.com/landjunge/tollgate/blob/d07c3ffb7513473a3de1c87bd01e9a1c9ea39c85/src/tollgate/cost.py), [Event-Emitter](https://github.com/landjunge/tollgate/blob/d07c3ffb7513473a3de1c87bd01e9a1c9ea39c85/src/tollgate/authority_emit.py).
- Sicherheitsprüfung „Eingefügter Text.txt“, Stand 3. Oktober 2026: acht Prüfbereiche von Identität über Budget bis Recovery/Audit. Die Entscheidungen oben beantworten diese Befunde; sie ersetzen keinen unabhängigen Implementierungsreview.

Externe Primärquellen, am 3. Oktober 2026 geprüft:

- [OWASP Authorization Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html): minimale Rechte, standardmäßige Ablehnung und Prüfung jeder Anfrage.
- [OWASP Secrets Management Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html): Geheimnislebenszyklus, Widerruf, Rotation und geschützter Transport.
- [RFC 8693, Abschnitt 1.1](https://www.rfc-editor.org/rfc/rfc8693.html#section-1.1): handelnder Akteur und verantwortliches Subjekt sind bei Delegation unterscheidbar. Dieser Plan behauptet weder eine bestehende OAuth-Implementierung noch eine Sicherheitsgarantie allein durch diesen RFC.

Die konkrete Aufteilung in Executor, Budgetjournal und Produktphasen ist eine
Projektentscheidung aus den Befunden, keine von diesen Quellen zertifizierte
Architektur.

## 15. Notizen, Grundgedanken und verbindliche Planprüfung

Ergänzt am 3. Oktober 2026 nach ausdrücklichem Nutzerauftrag. Diese Regeln gelten
produktübergreifend, auch für bestehende Tools. Der Sicherheitsplan oben bleibt
erhalten; dieser Abschnitt erweitert die Arbeitsweise, nicht bestehende Rechte.

**Der Mensch darf unsortiert denken; die KI übernimmt das Einordnen.** Sie trennt
Grundgedanke, Entscheidung, Aufgabe, Frage und belegtes Ergebnis, ordnet sie dem
bestehenden Zusammenhang zu und erhält Herkunft sowie Begründung. Ein flüchtiger
Gedanke wird nicht still zum Bauauftrag. Ausdrücklich getroffene Entscheidungen
werden dagegen festgehalten und angewendet. Philosophische Gedanken gehören mit
ihrem Sinn und ihren Folgen dazu; sie sind keine ungeprüften Tatsachenbehauptungen.

Leitgedanken: **einmal durchdenken, oft zuverlässig ausführen**; Nutzen für den
Tool-Nutzer ebenso wie für die Entwicklung; **GELD – GOLD – ENERGIE** als Erinnerung,
Zeit, Geld, Aufmerksamkeit und Rechenressourcen bewusst einzusetzen. Wiederverwendung
ist ein gewünschter Nutzen, keine gemessene „100000 %“-Einsparung.

Vor Ausführung jedes Plans gilt:

1. Ziel und beobachtbaren Nutzen festlegen; vorhandenen Code und aktuellen
   Arbeitsstand lesen.
2. Plan gegen diese GOLDENRULES prüfen. Widersprüche vor dem Bauen auflösen.
3. **Was kann weg?** Erledigte, doppelte, überholte oder für das Ziel unnötige
   Schritte aus dem aktiven Plan nehmen und den Grund im Verlauf erhalten.
   Daten-, Sicherheits- und Abnahmeanforderungen nicht als „Ballast“ streichen.
4. Vorhandene Module und Prüfabläufe verwenden; nur die tatsächlich fehlende
   Funktion ergänzen. Keinen parallelen Plan oder eine konkurrierende Regeldatei
   anlegen. Entscheidend sind klare Zuständigkeiten, kleine Schnittstellen und
   verständlicher, wartbarer Code; keine neue Abstraktion ohne konkreten Bedarf.
5. Modell und Arbeitsweg passend zur Aufgabe wählen, Abnahme durchführen, Ergebnis
   und Belege festhalten. Danach ohne Umweg im bereinigten bestehenden Plan weiter.

## 16. Nutzerprüfung, Hilfe, Voice und Erklärvideos

**Hilfe/Voice folgt der für ThreadDesk vereinbarten Ausgestaltung.** Diese wird als
wiederverwendbarer Ablauf auf die anderen Tools angewendet. Der genaue frühere
Voice-Entwurf liegt dieser Fassung nicht vor; vor seiner Umsetzung muss der
Originalbeschluss verknüpft und mit dem Code abgeglichen werden. Weder eine neue
Voice-Architektur noch bereits vorhandene Sprachhilfe wird hier behauptet.

Für jedes relevante Nutzerziel entsteht ein durchgehender, wiederholbarer Ablauf:
Vorbereitung, tatsächliche Bedienung, erwartetes sichtbares Ergebnis, Fehlerweg
und Wiederherstellung. Er prüft den Weg, den ein Nutzer wirklich benutzt,
einschließlich passender Desktop-/Browser-Umgebung. Ein reiner Backend-Test
beweist keinen funktionierenden Speichern-Dialog in einer nativen App.

Aus diesen **erfolgreich geprüften Nutzer-E2E-Abläufen** werden verständliche
Erklärvideos und die dazugehörige Hilfe abgeleitet. Prüfschritte, Hilfetext und
Video verweisen auf dieselbe Ablauf-ID und den geprüften Versionsstand. Die
Aufnahme zeigt den echten Ablauf mit synthetischen Daten; kein nachgestellter
Erfolg und keine privaten Arbeitsinhalte. Erklärungen zeigen Ziel, Handlung und
Ergebnis; bei einer relevanten Bedienänderung werden Prüfung, Hilfe und Video
gemeinsam aktualisiert. Ein Video ersetzt weder automatisierte Assertions noch
die Abnahme. Voice ergänzt den verständlichen Ablauf; lesbare Hilfe bleibt nutzbar.

Einmal gewonnene Prüfabläufe werden wiederverwendet und **rückwirkend auf bestehende
Tools und Funktionen angewendet**. Vorhandene Tests zuerst zuordnen, Lücken gezielt
schließen; keine kosmetischen Doppeltests. Je Tool werden Datenverlust/Recovery,
wichtige Integrationen und häufige Nutzerabläufe zuerst geprüft. Ein übertragener
Test zählt erst nach tatsächlichem Lauf für das jeweilige Tool und seine Version
als bestanden. „Nicht geprüft“, „fehlgeschlagen“ und „bestanden“ bleiben getrennt.
Die 22 Sicherheitsfälle oben sind dadurch weiterhin nicht automatisch erfüllt.

Die gemeldete ThreadDesk-Sicherungsstörung hat Vorrang: tatsächlichen Fehlerpfad
eingrenzen, Sicherung und Öffnen in einem getrennten Arbeitsbereich prüfen,
Originaldaten erhalten. Notion bleibt bis zur nachgewiesenen Umschaltung das
Arbeitsgedächtnis. Eine erfolgreiche Serverantwort allein ist keine Auslieferung
einer nutzbaren Sicherungsdatei an den Nutzer.

### Verbindliche Reihenfolge: Browser vor Voice und nativen Apps

Zwischenentscheidung des Nutzers vom 3. Oktober 2026: **Zuerst müssen alle
vorgesehenen Nutzerabläufe im Browser funktionieren und dort geprüft sein. Aktive
Voice-Hilfe sowie Bau und Auslieferung nativer Mac-, Windows- und Linux-Apps
kommen zum Schluss.** Das betrifft auch erneute native Build-Runden; ein grüner
Backend-Test allein erfüllt die Browser-Abnahme nicht.

Die Browser-Abnahme verwendet den bereinigten aktuellen Funktionsumfang, keine
unbegrenzte Liste künftiger Funktionen. Fehlende oder fehlerhafte Browserabläufe
werden sichtbar nachgeführt und abgearbeitet. Hilfe-/Video-Abläufe können dabei
aus echten Prüfungen vorbereitet werden; aktive Voice-Integration und native
Pakete werden dadurch nicht vorgezogen. Bereits erkannte kleine Codekorrekturen
am Desktop dürfen als nachvollziehbarer Entwurf erhalten bleiben; sie sind kein
Nachweis einer getesteten oder ausgelieferten nativen App.

## 17. Aufgabenbezogene Modellwahl und kleiner Whiteboard-Hook

**Wähle das günstigste verfügbare und zugelassene Modell, das die konkrete Aufgabe
mit ausreichender Qualität erfüllt.** Qualität, Datengrenzen, erforderliche
Werkzeuge, Kontextumfang, Zuverlässigkeit und Abnahmekriterien sind Bedingungen;
Kosten werden innerhalb dieser Bedingungen minimiert. Einfach das billigste
Modell zu wählen, obwohl es die Aufgabe nicht schafft, erfüllt die Regel nicht.

Der geplante kleine Hook am Whiteboard prüft vor einer KI-Aufgabenübergabe und
bei einer wesentlichen Aufgabenänderung:

- Was muss erreicht und woran wird Erfolg erkannt? Welche Fähigkeiten, Daten,
  Rechte, Werkzeuge und Zeitgrenzen werden tatsächlich gebraucht?
- Reicht ein vorhandener deterministischer Ablauf, ein vorhandenes Ergebnis oder
  eine lokale Lösung ohne neuen bezahlten Modellaufruf?
- Welches zulässige Modell erfüllt die Anforderungen mit den niedrigsten
  erwarteten Gesamtkosten einschließlich absehbarer Wiederholungen und Prüfung?
- Sind Modellverfügbarkeit, Preisgrundlage und Budget ausreichend aktuell?
  Unsichere Angaben kenntlich machen; keine erfundenen Preise oder Energiezahlen.

Der Hook hält Aufgabe, Auswahl, kurze Begründung, Preis-/Fähigkeitsstand und
erwartete Kosten fest; tatsächliche Kosten und Qualitätsbefund kommen nach dem
Lauf dazu, soweit messbar. Energie wird nur mit belastbaren Daten beziffert;
Tokenzahl und Antwortzeit sind nicht automatisch gemessener Stromverbrauch.
Er verwendet vorhandene Metadaten und einfache Regeln zuerst und darf nicht für
jede triviale Aufgabe selbst einen teuren Modellaufruf auslösen.

Reicht ein Modell nachweislich nicht, folgt eine begrenzte, begründete Eskalation
innerhalb der Freigabe und des Budgets. Kein endloses Wiederholen, keine stille
Budgeterhöhung, kein Wechsel über die Datengrenze. Bei fehlender geeigneter Option
wird die Aufgabe sichtbar angehalten. Ein Modellwechsel erteilt keinerlei neue
Rechte und umgeht weder 4AllPass noch TollGate.

Der Hook ist eine kleine Ergänzung am bestehenden Übergabepunkt, kein neuer
Orchestrator. Der ThreadDesk-Kern führt dadurch keine externen Agenten aus.
**Status: verbindlicher Baupunkt, noch nicht implementiert.** In der bestehenden
Baufolge nach den akuten Datensicherungsfehlern einordnen; nicht als parallele
Baustelle vorziehen. Die zukünftige Abnahme umfasst einfache und schwierige
Aufgaben, unzureichende Qualität, veraltete Preise, Budgetmangel und Datenfreigaben.


## 18. Verbindliche Designregeln und Überarbeitung vom 3. Oktober 2026

**Erster Durchgang. Die anschließende Nutzerkritik und der gemeinsame Kern in
Abschnitt 19 ergänzen und präzisieren diesen Stand. Der Nachweis mit 172 Tests
bezieht sich auf Commit a443dcd, nicht auf spätere Änderungen.**

Der Nutzer verwirft die uneinheitliche Oberfläche ausdrücklich: Schriften,
Button- und Feldgrößen, Abstände und Flächennutzung müssen zusammenpassen.
Diese Entscheidung ersetzt die bisherigen R2-Maße 28/32 Pixel und 10-Pixel-Text.
Sie gilt für Schreibtisch, Wissen, Karte, Daten, Import und Dialoge einschließlich
Deutsch/Englisch, langer Inhalte, Leer- und Fehlerzustände.

### Gemeinsame Regeln

- Eine lokal verfügbare Systemschrift; keine zusätzlichen Webfonts. Vier feste
  Rollen: 12 Pixel für Metadaten, 14 für Lesetext und Bedienung, 16 für Abschnitte,
  24 für Seitentitel. Normale Browser-Vergrößerung bleibt nutzbar. Keine zufälligen
  Browser-Standardgrößen, Versalienüberschriften oder Schriftwechsel in Formularen.
- Alle Aktionsbuttons, Reiter und einzeiligen Felder haben dieselbe Höhe:
  40 Pixel, bei grobem Zeigegerät gemeinsam 44 Pixel. Keine kleinere „compact“-
  Variante. Gleiche Aktionen einer Gruppe teilen Breiten; freie Texteingaben
  nutzen den Rest. Mehrzeilige Inhalte und Thread-Zeilen dürfen mit Inhalt wachsen.
- Abstandsreihe 4/8/12/16/24/32 Pixel. 8 zwischen verbundenen Bedienelementen,
  16 für Panelinnenraum und zwischen Arbeitsflächen, 24 für getrennte Abschnitte.
  Formen, Labels, Bedienelemente und Überschriften an gemeinsamen Linien ausrichten.
- Dunkle ruhige Flächen, klare lesbare Texte, Akzent für Hauptaktion/Auswahl,
  Status zusätzlich als Text. Ein einheitlicher eckiger Komponentenstil; Formen
  der Wissenskarte behalten ihre Bedeutung. Sichtbarer Tastaturfokus.
- Desktop: Threadliste und Raum links, Arbeitsinhalt in der Mitte, Werkzeuge rechts.
  Arbeitsbereiche füllen die verfügbare Fläche. Bei schmalem Fenster werden Spalten
  geordnet untereinander gestellt; keine abgeschnittenen Aktionen oder überbreiten
  Textzeilen. Eine Karte darf als zweidimensionale Arbeitsfläche bedient werden.
- **Keine sichtbaren Scrollbalken.** Scrollen per Rad, Trackpad, Touch und Tastatur
  bleibt erhalten. Innere Scrollflächen sind fokussierbar und benannt; Fokus ist
  sichtbar. Inhalte nicht mit `overflow:hidden` unzugänglich machen. Das Verbergen
  der Balken ist ein ausdrücklicher Nutzerwunsch, keine allgemeine Empfehlung für
  Barrierefreiheit. Keine pauschale WCAG-Konformitätsbehauptung.
- Hilfedialog: im Fenster scrollbar, Fokus beim Öffnen hinein und beim Schließen
  zurück; Escape schließt. Hintergrundbedienung während des Dialogs gesperrt.
- Bestehende Funktionen und Datenspeicherung erhalten. Groks Nutzer-E2E-/Medien-
  Auftrag bleibt bestehen; Screenshots dieser Überarbeitung sind keine fertigen
  Erklärvideos. Native Builds und aktive Voice bleiben nachgeordnet.

### Recherchegrundlage und eigene Festlegung

Carbon liefert Rollen für Typografie und Komponenten, konsistente Buttonmaße
und eine Abstandsreihe. Die hier gewählten vier Schriftrollen, 40-Pixel-Höhe und
ThreadDesk-Flächenaufteilung sind unsere konkrete Produktentscheidung, keine
Behauptung, Carbon verlange überall genau diese Werte. MDN beschreibt, dass
`scrollbar-width:none` die Scrollbarkeit erhält und zusätzliche Tastaturwege
wichtig sind. W3C Reflow ist die Grundlage für die Prüfung schmaler Ansichten.

- [Carbon: Typografie](https://www.carbondesignsystem.com/building-blocks/foundations/typography/type-sets)
- [Carbon: Button-Spezifikation](https://www.carbondesignsystem.com/building-blocks/core/components/button/specifications)
- [Carbon: Abstände](https://www.carbondesignsystem.com/building-blocks/foundations/spacing/overview)
- [MDN: scrollbar-width](https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/Properties/scrollbar-width)
- [W3C: Reflow](https://www.w3.org/WAI/WCAG22/Understanding/reflow.html)

### Umsetzungsplan und Abschluss

1. Gesicherten Stand `accept/browser-coverage` bei `d3fdf51` übernehmen und alle
   vorhandenen Ansichten erfassen. Erledigt; eigener Branch `design/unified-interface`.
2. Gemeinsame Tokens und Komponenten korrigieren, widersprüchliche Überschreibungen
   entfernen, alle Ansichten damit aufbauen. Umgesetzt.
3. Im echten Browser mit synthetischen Daten prüfen: Desktop, schmales Fenster,
   320-Pixel-Reflow, beide Sprachen, lange Texte, Leer-/Fehlerzustände, Dialog und
   Tastatur-Scrollen. Vorhandene Funktionsprüfungen für betroffene Seiten ausführen.
   Abgeschlossen: 172 Tests bestanden; Umfang und Grenzen in COVERAGE.md.
4. Auffälligkeiten korrigieren, Ergebnis mit Grenzen in COVERAGE festhalten,
   Änderungen pushen und im bestehenden Notion-Plan verknüpfen. Kein nativer Build.

Die zusätzliche Browser-Abnahme `828320d` wurde während der Designarbeit
übernommen. Der aktuelle Prüfstatus steht unter TD-DESIGN-01 in COVERAGE.md;
die dort genannte Umgebung begrenzt den Nachweis. Keine Abnahme der konkreten
Nutzerinstallation und kein Ersatz für Groks Hilfe-/Videoarbeit.


## 19. Gemeinsame Bedienbasis für die fünf Produkte

### Auftrag und Entscheidung

Daniel am 3. Oktober 2026: Das momentane Design klingt wie „Bahnhofgeräusche“.
Am Ende sollen alle fünf Tools dieselbe Melodie spielen. Notion-Entscheidungen
sind zu prüfen, nicht blind abzuschreiben. Der Auftrag umfasst die gemeinsame
Gestaltung für **NetzwerkPunkt, Gnom-Hub-V1, ThreadDesk, TollGate und 4AllPass**.
Die fünf Namen stammen aus dem bestehenden Markenauftrag; NetzwerkPunkt ist
hier die Dachoberfläche. Agent-X-Files und versteh-mir sind nicht still als
fünftes Produkt umgedeutet worden.

Die erste Vereinheitlichung der Maße war unzureichend: In ThreadDesk hatten
Bearbeitung, Status, Verlauf, Notizen, Dateien, Modellwahl und Übergabe fast
gleiches Gewicht. Das Problem ist die Gewichtung der Arbeit, nicht nur Farbe.

| Frühere Vorgabe | Entscheidung | Begründung |
|---|---|---|
| Gemeinsame Familie, eckig, Systemschrift, Klartext | Behalten | Wiedererkennung, Offline-Fähigkeit und Verständlichkeit |
| R2: 10/12/14/16, 28/32 und später 20 px Höhe | Ersetzen durch 12/14/16/24 und 40 px | Widersprüchliche historische Zahlen; Lesbarkeit und gleichartige Bedienung haben Vorrang |
| Alle Funktionen gleichzeitig in Karten | Ersetzen | Arbeitsaufgabe sichtbar, sekundäre Details bei Bedarf; keine Wand gleichwertiger Formulare |
| Violett für jede Aktion im ersten ThreadDesk-Durchgang | Ersetzen durch neutrale Hauptaktion | Produktmarke ist keine zusätzliche Status- oder Aktionssprache |
| Status nur mit Farbe | Weiter untersagt | Text und Bedeutung bleiben auch ohne Farbwahrnehmung verständlich |
| Marken und Produktgrenzen | Behalten | Gemeinsame Gestaltung vereinigt weder Geheimnisse noch Ausführungsrechte |
| Websites zuvor nur mit Extraauftrag | NetzwerkPunkt in den aktuellen Familienauftrag aufnehmen | Die Nutzeranweisung umfasst alle fünf; andere öffentliche Marketingseiten bleiben gesonderte Arbeit |

### Ein Kern, verschiedene Aufgaben

**Source of truth:** `src/threaddesk/ui/static/networkpunkt.css`, Version 0.1.
Der vorläufige Ort ist das Repository des ersten Anwenders, keine zweite
Regeldatei und kein neues Produkt. Regeln bleiben hier. `style.css` enthält
ThreadDesk-Aliase, keine eigene zweite Farb- oder Größentabelle.

Der Kern enthält Grundflächen, Schriftrollen, Abstände, Bedienhöhe, Zustände,
Fokus sowie wiederverwendbare Buttons, Felder, Navigation, Hinweise und native
aufklappbare Bereiche. Namen beginnen mit `np-`. Er hat keine Abhängigkeit von
React, Alpine, HTMX, einem CSS-Framework, Google Fonts oder einem Server.
`networkpunkt.js` ist optional: Es merkt ausschließlich offene/geschlossene
Bereiche in der Browser-Sitzung und öffnet Bereiche für Tastaturkürzel. Die
native Details-Bedienung funktioniert auch ohne dieses Modul.

- **Orientierung:** Produktname und Navigation bleiben an vertrauten Orten.
- **Arbeitsbereich:** Titel, nächster Schritt und Aufgabe dominieren. Formulare
  zeigen Inhalt vor Nebenparametern. Eine hervorgehobene Hauptaktion je aktuellem
  Arbeitsbereich; Nebenaktionen neutral und ruhiger.
- **Ergänzungen:** Details, Verlauf, seltene Einstellungen und Zusatzwerkzeuge
  bleiben benannt erreichbar. Fehler, Sperren, Freigabeumfang und Konsequenzen
  dürfen nicht aus gestalterischen Gründen versteckt werden.
- **Flächen:** Grundfläche `#121316`, Arbeitsfläche `#1a1c20`, Auswahl/Hover
  `#25282e`; Text `#edf0f4`, Nebentext `#afb6c1`. Rahmen eines Eingabefelds
  `#808996`, dekorative Trennlinie `#353940`. Markenfarbe nur an Markenpositionen.
- **Rollen statt Einzelfälle:** vier Schriftrollen und dieselbe Abstandsreihe
  wie Abschnitt 18. Kein eigenes Größen- oder Farbsystem je Tool.
- **Bewegung:** keine zusätzliche Animation als Ersatz für Hierarchie.
  Reduzierte Bewegung respektieren. Browser zuerst, native Apps und aktive Voice
  zuletzt. Groks Hilfeproduktion soll auf den geprüften Oberflächen aufbauen.

### Prüfbare Artefakte

- [Figma-Grundlage](https://www.figma.com/design/B9Cj8P12JwXo7BGmW3Icu0?node-id=2-59):
  51 Variablen in zwei Sammlungen, davon 27 semantische Aliase, vier Textstile,
  eine geprüfte Familientafel. Kein fertiges Figma-Komponentenpaket behauptet.
  Roboto ist dort der vorhandene Fallback aus dem Browser-Schriftstack;
  die Browserfassung nutzt weiterhin die jeweilige Systemschrift.
- `src/threaddesk/ui/static/design-reference.html`: interaktive Vergleichsansicht
  aller fünf Produkte, identische CSS-Datei, Desktop-Aufbauprobe,
  Haupt-/Neben-/Gefahren-/Deaktiviert-Zustände und verständliche Feldfehler.
  Ausdrücklich synthetische Gestaltungsprobe, keine echte Produktfreigabe.
- ThreadDesk: Kopf und Navigation beruhigt, Threadpflege und Zusatzwerkzeuge
  öffnen sich bei Bedarf, geöffnete Bereiche bleiben nach Speichern/Neuladen
  erhalten. Tastaturkürzel öffnen ihren Zielbereich. Nächster Schritt sichtbar,
  Fortschrittseingabe vor dem vergangenen Verlauf.

### Übernahmeplan ohne fünf neue Entwürfe

| Produkt | Adapter / Aufgabe | Stand |
|---|---|---|
| ThreadDesk | `base.html` lädt den Kern; alte Variablen aliasieren `--np-*`; echte Browserabläufe erhalten | Implementiert auf Design-Branch; aktueller Prüfstand in COVERAGE |
| 4AllPass | `frontend/src/tokens.css` auf dieselben Rollen abbilden; React-Komponenten verwenden dieselben Klassen/Zustände; Freigabeumfang und Sperrstatus sichtbar | Adapter implementiert; Prüfbelege im Produkt-Repo; vollständige Nutzerabnahme offen |
| TollGate | eingebetteten Stil in `src/tollgate/dashboard_html.py` auf denselben Kern abbilden; Allow/Deny und Begründung unverändert klar trennen | Adapter implementiert; Prüfbelege im Produkt-Repo; vollständige Nutzerabnahme offen |
| Gnom-Hub-V1 | gemeinsame Navigation/Felder/Aktionen übernehmen; Agentenfarben nur als Identifikation; Senden und Ausführen getrennt lassen | Legacy-Desk und V4 adaptiert; Qualitätslauf und lokale Browserwege geprüft; Pipeline-Abnahme unverändert offen |
| NetzwerkPunkt | Orientierung und Produktzugänge aus derselben Familie; Dachmarke behalten; keine zusätzlichen aktiven Steuerfunktionen erfinden | Startseiten-Code adaptiert und lokal geprüft; Live-Seite noch nicht veröffentlicht |

Bei Übernahme die benötigten lokalen Quelldateien einer festgehaltenen Git-Version
kopieren (CSS immer, JavaScript nur bei verwendeten Interaktionen), alte Tokens über einen kleinen Adapter abbilden und die
Standard-/Hover-/Fokus-/Fehler-/Deaktiviert-Zustände prüfen. Keine Laufzeit-CDN
und keine automatische Aktualisierung fremder Repositories. Markenassets aus
dem separaten Grok-Auftrag bleiben produktspezifisch. Gemeinsame Änderungen
werden im Kern gemacht und in allen fünf Vergleichsansichten geprüft.

Die Abnahme pro Produkt umfasst den echten Hauptablauf, Nebenaktionen,
Fehler/Sperren, lange Inhalte, DE/EN, Tastatur und Desktop-Fenster. Erst dann
ist ein Produkt übernommen. Die gemeinsame Gestaltungsprobe allein zählt
nicht als Umsetzung oder Abnahme der fünf Produkt-Repositories.

### Forschung und Grenzen

[GOV.UK Buttons](https://design-system.service.gov.uk/components/button/) begründet
die Zurückhaltung mit mehreren gleichgewichtigen Hauptaktionen.
[NN/g Progressive Disclosure](https://www.nngroup.com/articles/progressive-disclosure/)
begründet die schrittweise Freilegung sekundärer Funktionen. Die konkrete
Aufteilung und Zahlen bleiben unsere begründete Produktentscheidung.
Carbon, W3C und MDN aus Abschnitt 18 ergänzen diese Grundlage.

Die Bezeichnung „fertig“ setzt die sichtbare Nutzerabnahme voraus; eine grüne
Testsuite ist kein Beleg, dass Daniel das Design akzeptiert hat. Diese Fassung
ist ein überprüfbarer gemeinsamer Kern mit ThreadDesk-Implementierung.


### Präzisierung durch Daniel: kein Responsive-Pflichtziel

Im selben Arbeitsgang ausdrücklich entschieden: Die Werkzeuge brauchen keinen
kompromisshaften automatischen Mobilumbau. **Desktop-Arbeitsplatz zuerst.**
Das ersetzt die entsprechende Reflow-/Mobilanforderung aus Abschnitt 18 und
dem ersten Entwurf von Abschnitt 19; historische Prüfergebnisse bleiben datiert.

- Gemeinsame Desktop-Komposition mit Navigation links, Arbeit in der Mitte,
  Ergänzungen rechts; keine Breakpoints, die diese Bereiche neu stapeln.
- Vorgesehene kleinste Arbeitsfläche: 1180 × 760 CSS-Pixel, Referenz 1440 × 900.
  Das ist die Implementierungsfestlegung für diesen Entwurf, kein gemessener
  Bildschirm des Nutzers. Größere Fenster geben dem Arbeitsbereich mehr Raum.
- 40 Pixel Bedienhöhe in diesem Desktop-Entwurf. Der optionale 44-Pixel-Token
  bleibt als Reserve, wird aber nicht automatisch über Pointer-/Viewportregeln
  aktiviert. Mobile/Touch-Produkte sind gesonderte spätere Entwürfe.
- Unterhalb der vorgesehenen Arbeitsfläche bleibt dieselbe Komposition per
  Scrollen erreichbar. Vergrößerung, lange Texte und Tastaturfokus dürfen keine
  Daten oder Aktionen unerreichbar machen. Das ist kein Mobil-Layout und keine
  WCAG-Reflow-Konformitätsbehauptung.
- Die Prüffälle richten sich nach dieser Entscheidung: Desktop-Maße und
  Erreichbarkeit bei kleinerem Ausschnitt, nicht mehr Smartphone-Reflow.

### Ergänzung zur Zusammenarbeit und Übernahme · 03.10.2026

Daniel muss Figma nicht verwenden oder lernen. Ergebnisse werden in den echten
Werkzeugen und als direkt sichtbare Vorschau beurteilt. Figma darf intern helfen.
Seine angekündigte Idee zur Umsetzung mit sehr wenigen Werkzeugen bleibt
geparkt, bis er sie erklärt; keine erfundene Ausarbeitung oder neue Abhängigkeit.

Alle vier neuen Adapter pinnen dieselbe CSS-Datei auf ThreadDesk `b0b6815`.
Die unveränderte lokale Kopie und kleine Produktspezialfälle vermeiden neue
Build-Werkzeuge und Laufzeitdienste. Umsetzung ist nicht gleich vollständige
Nutzerabnahme; der genaue aktuelle Prüfumfang steht in COVERAGE und den
`docs/usability/design-2026-10-03/checks.json` der Produkt-Repositories.
