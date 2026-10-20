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

- 32 reine Node-Zustandsfälle grün: unknown/connecting/disconnected/error,
 falsche Bindungen/Typen/TTL/Sequenzen/Generationen/Instanzen, Timeout/
 Uhr-Rücksprung/Invalidate, AP4 allowed Nutzer/Tresor und separate Vault-TTL,
 Sperren/unknown, Ausfall/Wiederverbindung; KB/TD/TollGate nie Puls.
- 9 echte Chromium-Rendererfixturefälle grün: DE/EN, tatsächliche Tastatur/
 Tooltip-Escape, Inflight- und schneller Doppelklick, Open setzt keinen Ring,
 unklarer Ausgang mit später Antwort, periodischer TTL-Tick ohne manuelle
 Aktualisierung, Remount genau ein Timer/Destroy null Timer, keine Wiederbelebung,
 fehlender Farbtoken neutral, feste Bounds auch bei320px und reduced motion.
 Nur Ring-Pseudoelement animiert12s/1.0..0.9; Originalbildopacity bleibt1.
- Bundle-/Assetintegrität und17 vorhandene UI-Assetregeln grün. Gemeinsamer
 pytest-Aufruf28/28; er enthält den Wrapper für die32 Nodefälle, keine
 Doppelzählung als vollständige Produktabnahme. Keine neuen Dependencies.

Kommando: `.venv/bin/python -m pytest -q tests/test_appbar.py tests/test_ui_assets.py`.
Private Logs im ursprünglichen Fortsetzungsordner: e05-pure-state.log und
e05-renderer-review-candidate.log. Die Browserfixture fängt ausschließlich
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
