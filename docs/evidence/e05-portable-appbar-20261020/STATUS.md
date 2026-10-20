# E05 / UI-01 — reine portable Grundlage1.0.0

20.10.2026, Basis ThreadDesk-main b63fbd2. Autor: plan_contract_matrix;
unabhängiger Source-/Browserreview und PR-CI folgen. Vollplan§13 bleibt
maßgeblich: KiraBridge zuerst einbinden, dann TD/AP. Keine Templates oder
produktiven Imports/Mounts, keine Liveinstallation. Die separate belegte
Wordmarkkorrektur ist PR81 und gehört nicht in diesen Renderer-Diff.

## Tatsächlicher Umfang

Drei kleine native ES-Module/CSS plus versionierter fester Katalog/Bytebundle;
kein React/Framework/Pluginbus und kein Netz-/Storage-/Hostöffnen im Renderer.
Der bestehende NP-Kern bleibt unverändert. Eigene Header/Wordmarkfarben werden
nicht ersetzt. Die Font-/Formenwächter erhalten genau eine begründete Ausnahme
für den ausdrücklich verlangten runden Statusring, nicht für Bedienflächen.

Nur passende, frische Metadaten vom bereits authentisierenden Hostadapter
dürfen bestätigen: erwartete App/Verbindung/Peer/Instanz, aktuelle lokale
Generation, steigende Sequenz,2s-Checkdeadline und maximal15s ab Checkbeginn.
AP4 zusätzlich exakt erlaubter Nutzer/Tresor und eigene Vault-TTL. Renderer
prüft Zuordnung/Form/Frische, ist selbst KEIN Auth-/Gerätebesitznachweis.
Offene/fehlende Adapter bleiben unknown; Start/PID/Transport reichen nicht.
Nur AP4 darf pulsieren, nie Bridgearbeit. Ablauf stoppt den Puls ohne falsches
locked. Öffnen ist ein separater fester Hostadaptervertrag mit Dedupe, Deadline,
Vorgangszuordnung und ohne automatischen Retry; es setzt nie connected.

## Assets/Farben und Nutzerfeedback

Vorhandene freigegebene TD/AP4-48px-PNGs unverändert kopiert; Herkunft/Gitpins
in networkpunkt-appbar-assets.json, vollständige Bundlefingerprints separat.
KiraBridge-Bild weiterhin nicht zugeordnet, kein Ersatzlogo. TollGate nur noch
nicht zugeordnet, kein pauschaler Fehlbestandsbefund. TD-Ringfarbe aus
brand/README #b99cff. Keine dokumentierte aktuelle AP4-Ringfarbe in AP4-
brand/README, containers.json oder tokens.css nachweisbar; Pixelheuristik
wurde verworfen. Standardkatalog AP4farbe=null hält neutral. Erst ein
vertrauenswürdig konfigurierter Host darf eine dokumentierte benannte
Toolfarbe liefern; synthetische Browserfarbe ist KEINE Markenfreigabe.

Maße24/32/40px mit4px Abstand sind ausschließlich der vorläufige Fixturestand.
Daniels aktuelle Icongrößenmeldung ist noch keiner Oberfläche zugeordnet,
daher weder Größenänderung auf Verdacht noch Nutzerabnahme behauptet.
NP-Regeln/Einbindungsvertrag: docs/contracts/appbar-v1.md.

## Wirklich ausgeführte Prüfungen

- 35 reine Node-Zustandsfälle grün: unknown/connecting/disconnected/error,
 falsche Bindungen/Typen/TTL/Sequenzen/Generationen/Instanzen, Timeout/
 Uhr-Rücksprung/Invalidate, AP4 allowed Nutzer/Tresor und separate Vault-TTL,
 Sperren/unknown, Ausfall/Wiederverbindung; KB/TD/TollGate nie Puls.
- 13 echte Chromium-Rendererfixturefälle grün: DE/EN, tatsächliche Tastatur/
 Tooltip-Escape, Inflight- und schneller Doppelklick, Open setzt keinen Ring,
 unklarer Ausgang mit später Antwort, periodischer TTL-Tick ohne manuelle
 Aktualisierung, Remount genau ein Timer/Destroy null Timer, keine Wiederbelebung,
 fehlender Farbtoken neutral, feste Bounds auch bei320px und reduced motion.
 Nur Ring-Pseudoelement animiert12s/1.0..0.9; Originalbildopacity bleibt1.
- Bundle-/Assetintegrität und17 vorhandene UI-Assetregeln grün. Gemeinsamer
 pytest-Aufruf32/32; er enthält den Wrapper für die35 Nodefälle, keine
 Doppelzählung als vollständige Produktabnahme. Keine neuen Dependencies.

Kommando: `.venv/bin/python -m pytest -q tests/test_appbar.py tests/test_ui_assets.py`.
Aktuelle private Logs im ursprünglichen Fortsetzungsordner:
e05-f3-author-green.log (enthält den35-Node-Wrapper).
Die vorigen Fixläufe bleiben als e05-author-regressions-green-node.log und
e05-author-regressions-green.log erhalten.
Die ursprünglichen b36-Logs e05-pure-state.log und
e05-renderer-review-candidate.log bleiben als historische32/28-Prüfstände erhalten. Die Browserfixture fängt ausschließlich
synthetische lokale Assetrequests ab, blockiert sonstiges Netz, startet einen
eigenen temporären Browserkontext und beendet ihn. Keine echte TD-/AP-/KB-
Verbindung, Nutzerkonten, Datenbank, Appstarts oder Userbrowserprofile beteiligt.
Keine Screenreader-/native/Host-/Verbund-/Voll-E05-Abnahme.

Früherer Autorfixturelauf7/8: ein Test versuchte einen absichtlich
aria-disabled-gesperrten erneuten Klick und lief in Playwrights korrekten
Enable-Wächter. Als erzwungenes Event prüft er nun tatsächlich den Dedupeguard;
dies war kein Produktfehler oder grüner Beleg. Danach alle oben genannten
Fälle mit aktuellem unverändertem Stand frisch grün.

## Noch offen

KiraBridge-Icon, belegter AP4-Brandfarbwert, zugeordnete Icongrößenmeldung,
KiraBridge-Ersteinbindung, echte abgesicherte Peer-/Status-/Openadapter,
danach TD/AP-Hosts und deren echte Nutzer-/Nativewege. Diese Grenzen blockieren
die reine Rendererprüfung nicht und werden durch sie nicht erledigt.

## Korrektur nach unabhängigem b36-Review

Der unabhängige Review von b36af8563f47f0d488d0f885a36b8ed99c33032b
fand zwei mittlere Zeitgrenzfehler und einen kleinen Tooltipfehler. Die alten
Quellen/Belege bleiben über refs/repairs/e05-reviewed-b36af85 und die privaten
Reviewdateien erhalten. Dieser Stand ist noch keine unabhängige Nachabnahme.

- F1: Nach beobachteten14s konnte ein partieller Wanduhr-Rücksprung das Alter
  auf1s verkürzen und Ring/Puls erhalten. Der gemeinsame je Vorgang verwendete
  Elapsedsampler hält Alter nicht sinkend und lässt jeden beobachteten Rücksprung
  von monotoner Uhr oder Wanduhr dauerhaft ablaufen. Pendingchecks und die vom
  Checkbeginn übernommene Verbindung/Vault-Lease verwenden denselben Sampler.
  Neue echte Antworten können erst über einen neuen Check wieder bestätigen.
- F2: Die Öffnungsdeadline verwendete zuvor nur die monotone Uhr. Wanduhr+5s
  bei stehender monotoner Uhr akzeptierte dadurch einen verspäteten opened-
  Ausgang. Jetzt gelten beide Uhren samt Rücksprungschutz für2s-Deadline und
 600ms-Dedupe. Ein unklarer Ausgang bleibt gesperrt, auch nach späterem Callback;
  ausschließlich explizites clearOpen nach Hostprüfung ermöglicht die Erholung.
- N1: Tooltips werden mit fester äußerer Maximalbreite und DOM-Bounds beim
  Anzeigen, Text- und Viewportwechsel horizontal geklemmt. DE/EN und beide
  Einträge bleiben bei320px erreichbar; unveränderte Icon-/Ring-/Buttonmaße.

Eigene neue Regressionen auf altem Produktstand: Node3rot/32grün und die fünf
gezielt gewählten Browserfälle rot. Nach Fix Node35/35, gesamter gezielter
Repo-Aufruf31/31. Darin12 echte Browserfälle und17 vorhandene UI-Assetregeln.
Zusätzlich dieselben unveränderten privaten Reviewerproben erneut ausgeführt:
Node5/5 und Chromium6/6. Dies sind Autor-Gegenproben, kein unabhängiger Review.
Private Logs: e05-author-regressions-red-node.log, -red-browser.log,
-green-node.log und -green.log; e05-reviewer-probes-green-node.log und
-green-browser.log. Unveränderte Reviewerprobendateien separat SHA256-erfasst
in e05-fix-reviewer-probe-SHA256SUMS. Keine Rechte-/Adapter-/Liveausweitung.

## Enge F3-Nachbesserung nach ef286-Nachreview

Der unabhängige Nachreview schloss F1/F2/N1, fand aber einen neuen mittleren
Fehler beim Verwenden desselben Samplers für die Mindestwartezeit: Nach einem
sofortigen opened und Wanduhr-Rücksprung bei mono+100ms lieferte age Infinity;
Infinity<600 war false und erlaubte einen zweiten Start. Der alte Stand
ef286c2edd60131dbb541a2280f252f0223f1dc7 bleibt unter
refs/repairs/e05-reviewed-ef286c2 sowie den bisherigen Logs erhalten.

Jetzt endet die aktive600ms-Wartezeit ausschließlich nach endlichem geprüftem
Alter>=600. Ein ungültiger Wert sperrt uncertain, auch nach sofortigem Erfolg;
Zeitfortschritt allein entsperrt nicht. Nach expliziter Hostprüfung/clearOpen
beginnt bei ungültiger Messung eine volle neue600ms-Wartezeit. Die2s-Deadline
bleibt unverändert fail closed. Keine Adapterrechte oder Liveflächen geändert.

Neue eigene echte Browserregression am unveränderten ef286:1rot (zweiter Start
nach100ms). Nach Fix gezielter Repo-Aufruf32/32 grün, darin35 reine Nodefälle
als ein Wrapper,13 echte Browserfälle,17 bestehende UI-Assetfälle und Hashes.
Die neue Regression prüft auch kein Blind-Retry nach10s sowie599/600ms nach
expliziter Recovery. Unveränderte Reviewerproben vom Autor erneut ausgeführt:
5 Node-/7 Browserfälle grün einschließlich test_cooldown_rollback.py. Keine
Änderung der privaten Reviewerfälle. Logs: e05-f3-author-red.log,
e05-f3-author-green.log, e05-f3-reviewer-node-green.log und
e05-f3-reviewer-browser-green.log. Unabhängige Nachprüfung bleibt offen.
