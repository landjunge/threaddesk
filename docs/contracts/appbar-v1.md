# UI-01 · portabler Renderer 1.0.0

Dies ist die reine gemeinsame Grundlage des bestehenden E05-Auftrags, keine
fertige Verbindung oder App-Einbindung. Quelle ist vorläufig ThreadDesk wie beim
NP-Kern (§19 GOLDENRULES). **Zuerst folgt KiraBridge; ThreadDesk/4AllPass sind
noch nicht eingebunden.** Kein bestehender Header, Markenname oder Markenfarbwert
wird durch diese Dateien verändert. Es gibt keinen verpflichtenden ThreadDesk-Hub.

## Versionierte lokale Übernahme

`src/threaddesk/ui/static/networkpunkt-appbar-bundle.json` nennt den kleinen
Dateisatz; `networkpunkt-appbar-SHA256SUMS` enthält vollständige Fingerprints.
Die benötigten Dateien einer konkreten Git-Version bewusst bytegleich lokal
kopieren, Hashes prüfen und den Quellpin im jeweiligen Host festhalten. Keine
CDN, automatische Repo-Aktualisierung, neue Dependency, Framework- oder
Pluginplattform. Der bestehende NP-CSS-Kern0.1 ist die Gestaltungsabhängigkeit;
seine vorhandenen Marken-/Schriftregeln werden nicht umgeschrieben.

Der Katalog1.0.0 enthält feste App-IDs, DE/EN-Namen, vorhandene Bilddateien,
eigene Toolfarbe und den Weg `host-adapter`. Die Installation liefert den
zugehörigen erlaubten Status-/Öffnungsadapter. Statuswerte können weder Icon,
Farbe, Reihenfolge noch ein Startziel bestimmen. Nur bekannte Suite-IDs sind
zugelassen; weitere Fachmodule sind keine zusätzlichen App-Icons.

- ThreadDesk: freigegebener48px-Dark-Export aus assets/design, bytegleich.
  Ringfarbe #b99cff aus bestehendem brand/README.
- 4AllPass: aktueller freigegebener AP4-Dark-Export aus brand/ap4, bytegleich;
  keine historische Elster. Kein belegter aktueller Ring-Brandtoken in
  brand/README.md, brand/ap4/containers.json oder frontend/src/tokens.css;
  Pixelheuristiken werden nicht als Markenentscheidung übernommen. Der
  Standardkatalog hält die Farbe deshalb null und die Statusanzeige neutral.
- KiraBridge: weiterhin kein zugeordnetes freigegebenes Bild. Kein Buchstabe,
  Fremdicon oder neu gezeichnetes Ersatzlogo. Deshalb noch kein Katalogeintrag.
- TollGate: Asset noch nicht diesem Modul zugeordnet; kein behauptetes Fehlen
  im Gesamtbestand. Später fester Eintrag plus erlaubter Adapter.

## Hostslot und Darstellung

Der Host reserviert später denselben Headerplatz nach seiner Produktmarke und
vor den eigenen Aktionen. Die Grundlage montiert **keinen** Host selbst.
Vorbereitete Fixturemaße:24px-Bild aus48px-Datei,32px-Ring,40px-NP-Bedienfläche,
4px-Abstand. Das ist ein technischer Prüfstand, keine sichtbare Nutzerabnahme;
Daniels aktuelles Feedback zur Icongröße ist noch einer Oberfläche zuzuordnen.
Eine daraus folgende Maßänderung wird zentral vorgenommen, nicht pro Host
anders erfunden. Keine automatische Touch-/Mobilgestaltung entgegen der
aktuellen NP-Präzisierung. Auch im schmalen Fixtureausschnitt bleibt der Zugang
erreichbar; dies ist keine Abnahme tatsächlicher Hostheader.

Die Katalogreihenfolge KiraBridge/ThreadDesk/4AllPass/TollGate ist unabhängig vom
Status; nur verfügbare konfigurierte Einträge erscheinen. Nativer Button mit
Textname/Status/Öffnungsaktion als aria-label, Tab/ShiftTab/Enter/Space, sichtbarem
Fokus und Tooltip bei Fokus/Hover, mit Escape schließbar. Der Tooltip wird
bei Anzeige, Text- und Viewportänderung innerhalb der sichtbaren Breite gehalten.
Kein Zusatzschloss.
Die Live-Region meldet semantische Änderungen, nicht jeden lokalen250ms-Tick.
Nur der AP4-Ring darf bei erlaubtem aktuellem Unlock langsam pulsieren:
12s, Deckkraft1.00…0.90, Glow10% Toolfarbe. Bild/Hitarea werden nicht animiert.
Reduced motion schaltet die Ringanimation aus; der Text bleibt eindeutig.

## Öffentliche API

ES-Module, ohne React/DOM-Bibliothek:

```js
import { mountAppBar } from "./networkpunkt-appbar.js";
const bar = mountAppBar(reservedElement, {
  catalog, locale: "de", peers: trustedExpectedBindings,
  colors: trustedNamedToolColors, // {appId:{value:"#RRGGBB",sourceRef:"belegter-Token"}}
  onOpen: allowedHostOpenAdapter
});
const ticket = bar.begin("4allpass");
// Erst nach Prüfung durch den vorhandenen authentisierten Hostadapter:
bar.receive("4allpass", ticket, verifiedMetadata);
// Alternativ bar.fail(appId, ticket, "error" oder "unknown").
// bar.reset(appId, newTrustedExpectedBinding) invalidiert alte Instanz/Generation.
// bar.setLocale("en"); bar.destroy();
```

Kein Netzwerk, Storage, PID-/Portscan, allgemeiner Shellaufruf, Fensteröffnen
oder fachlicher Auftrag im Renderer. `clock`/`wallClock` sind injizierbare lokale
Fixtureuhren; normale Hosts verwenden performance.now und Date.now.

## Statusadaptervertrag

Erwartete Bindung aus vertrauenswürdiger lokaler Installation:

```
{appId, connectionRef, peerRef, peerEpoch,
 unlockScope?: {userRef, vaultRef}}
```

`peerRef` muss das erwartete Gegenüber des vorhandenen authentisierten Kanals
bezeichnen, `peerEpoch` dessen bestätigte Instanz. Öffentliche IDs/Fingerprints
allein authentisieren nichts. Insbesondere darf der Adapter weder PID,
Transport-live, erfolgreichen Start noch health200 in `confirmed` übersetzen.
Wo der Kanal fehlt, bleibt der Status unknown. Ein frei gepostetes
`authenticated:true` ist kein Beweis und kein Feld dieses Vertrags.

Verifizierte, geheimnisfreie Metadaten aus diesem Adapter:

```
{v:1, appId, connectionRef, peerRef, peerEpoch, seq,
 state:"confirmed"|"connecting"|"disconnected"|"unknown"|"error",
 ttlMs:1..15000,
 vault?: {userRef,vaultRef,allowed:true,
          state:"locked"|"unlocked"|"unknown",ttlMs:1..connectionTTL}}
```

Der Renderer prüft Form/Zuordnung/Frische, **nicht** Authentisierung oder
Gerätebesitz. Der Hostadapter muss die echte Antwort an die angefragte
Verbindung und aktuelle erlaubte Nutzer-/Tresorzuordnung binden. Ein Boolean
ersetzt diese Prüfung nicht. Keine neuen Schlüssel, Secrets, Konten oder
Berechtigungen für die Darstellung. Keine Tresorobjekte, Inhalte, Tokens,
Passwörter, Grants, Budgets oder Aktivitätsdaten in diesem DTO.

Eine fehlende Toolfarbe muss aus dokumentierter Gestaltung kommen, benannt
durch den vertrauenswürdigen lokalen Hostadapter (`colors` mit sourceRef).
Statusantworten dürfen sie nicht liefern. Ohne diese Konfiguration bleibt die
Anzeige neutral; die Browserfixture verwendet ausdrücklich eine synthetische
Testfarbe, keine freigegebene AP4-Marke.

Pro Peer höchstens ein laufender lokaler Check; `begin` liefert dafür ein
unveränderliches lokales Ticket, kein Auth-/Netzprotokoll. Deadline2s; TTL maximal
15s und konservativ ab lokalem Checkbeginn, nicht ab einer verspäteten Antwort.
Der Host begrenzt seine tatsächlichen Abfragen auf vorhandenen4s- oder5s-Takt;
der reine Renderer fragt nichts ab. Gleiche/alte Sequenzen, falsche App/Verbindung/
Peer/Instanz, fremde Tickets, Zeitüberschreitung und ungültige Metadaten werden
verworfen. Reset/Verstecken/pagehide invalidieren die Generation. Lokale monotone
und Wanduhr werden gemeinsam konservativ bewertet; Schlaf oder Uhr-Rücksprung
darf kein altes Grün verlängern. Das je Vorgang beobachtete Alter sinkt nie;
ein beobachteter Rücksprung einer der beiden Uhren macht dessen Lease dauerhaft
ungültig, auch wenn die Uhr noch nach dem ursprünglichen Checkbeginn liegt.
Erst ein neuer Check kann wieder bestätigen. Es wird kein Status aus Storage restauriert.

`confirmed` mit gültiger Verbindung erzeugt den ruhigen eigenen Ring. Nur AP4
mit explizitem allowed:true und exakt erwartetem userRef/vaultRef darf zusätzlich
unlocked anzeigen. Eigene kürzere Vault-TTL endet ohne falsches locked; der
Verbindungsring darf dabei ruhig weiterleuchten. Locked ist ausdrücklich
gesperrt, unknown ausdrücklich unbekannt. Andere Apps erhalten niemals einen
Aktivitäts-/Unlockpuls. Ein fehlgeschlagener Check neutralisiert sofort.

## Fester Öffnungsadapter

`onOpen({appId,actionId,signal})` erhält nur feste Katalog-ID, lokalen Vorgangsbezug
und Abbruchsignal. Kein freies Ziel/Argument aus Projekt-/Thread-/Teamdaten.
Der Host mappt diese ID auf bereits erlaubtes festes Ziel und schützt Fokus/
Start sowie begrenzte Idempotenz selbst. Antwort:
`{actionId,outcome:"focused"|"opened"|"failed"|"unknown"}`.

Parallel-/Doppelklicks werden zusammengeführt (mindestens600ms). Deadline2s
mit derselben konservativen monotonen/Wanduhrmessung wie beim Status: Schlaf,
Wanduhrfortschritt bei stehender monotoner Uhr oder beobachteter Rücksprung
können einen verspäteten Erfolg nicht nachträglich akzeptieren;
unklarer Ausgang bleibt gegen weiteren Start gesperrt und hat keinen
automatischen Retry. Erst nach eigener Zielprüfung darf der Host
`clearOpen(appId)` aufrufen. Späte Ergebnisse ersetzen keinen neueren Vorgang.
Destroy signalisiert Abbruch; ein unkooperativer Adapter kann nicht vom
Renderer zwangsweise beendet werden, verändert aber dessen DOM nicht mehr.
Fehlendes Ziel/Fehler führen zu festen DE/EN-Handlungen, nie rohen Responses.
Ein Öffnungserfolg bestätigt **niemals** eine Verbindung oder Tresorfreigabe.

## Geprüfter und weiterhin offener Umfang

`python -m pytest -q tests/test_appbar.py tests/test_ui_assets.py` führt die
35 reinen Node-Zustandsprüfungen sowie echtes Chromium-DOM/CSS aus. Die
Browserfixture liefert nur freigegebene lokale Assets über abgefangene
Fixture-Requests; keine echte App, Verbindung, Konten, Datenbank oder Startziele.
DE/EN/Keyboard, Scope/TTL/Fehler/Wiederverbindung, Ring-/Bildgeometrie, reduzierte
Bewegung, Timerabbau und keine doppelten synthetischen Starts werden gemessen.
Das ist Renderer-/Accessibility-Verhalten, keine vollständige Screenreader-,
Nutzer-, Native- oder Verbundabnahme. Keine Vorlage wird produktiv importiert.

Offen bleiben KiraBridge-Asset, belegter AP4-Ringfarbwert, erste KB-Einbindung, abgesicherte echte
Öffnungs-/Statusadapter, danach TD/AP-Mounts und jeweilige native/Host-Abnahme.
Ein neuer Adapter erweitert nicht Tresor-, Projekt- oder Auftragsrechte.
