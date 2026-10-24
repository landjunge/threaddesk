# ThreadDesk Server & Sync

Dieser Entwicklungsstand ergänzt ThreadDesk um einen getrennten Browser-Server
und einen lokalen Sync-Client. Der Server verwendet den gemeinsamen
ThreadDesk-Kern für Projekt-Threads und Whiteboards. Er benötigt keinen Mac und
keine laufende KiraBridge. Der vorhandene Desktop-Server und dessen lokale
Zugriffsregeln bleiben getrennt.

Die Installationsdateien sind Vorlagen für eine eigene Installation. Ein
erfolgreicher nativer Linux-Betrieb, eine fertige Desktop-Anbindung und eine
Produktivfreigabe werden damit noch nicht behauptet. Den genauen Prüfstand
nennt der Entwicklungsbericht. Es gibt keinen automatischen Merge oder Release.

## Installation mit Docker und HTTPS

Voraussetzungen: vollständiger Quellcheckout dieses Branches, Docker mit Compose,
eine auf den Server zeigende Domain und erreichbare Ports 80/443. Wählen Sie
eine eigene Domain ohne URL-Pfad. Die Beispiele werden im Repository ausgeführt:

```sh
export THREADDESK_DOMAIN=server.example.org
docker compose -f packaging/server/compose.yaml build
docker compose -f packaging/server/compose.yaml run --rm app init --data-dir /data --user alice
docker compose -f packaging/server/compose.yaml up -d
```

Der Initialisierungsbefehl zeigt das zufällige Zugangstoken einmal an. Bewahren
Sie es privat auf, etwa in einem Passwortmanager. Die Serverkonfiguration enthält
nur seinen Hash. Der Browser benötigt das Token zum Anmelden; danach verwendet
er eine Sitzung. Für weitere Nutzer denselben Initialisierungsbefehl mit einem
anderen Nutzernamen ausführen. Jeder Nutzer erhält einen eigenen Datenbereich.
Dateien, Projektkennungen und Transferkennungen erlauben keinen Wechsel in einen
anderen Nutzerbereich.

Der laufende Server lädt die Nutzerliste beim Start. Nach dem Anlegen weiterer
Nutzer den App-Dienst neu starten, damit neue Zugangsdaten verfügbar werden:
`docker compose -f packaging/server/compose.yaml restart app`.

Caddy stellt HTTPS bereit. Der App-Port wird durch die Compose-Datei nicht am
Host veröffentlicht. Zertifikate und App-Daten liegen in getrennten dauerhaften
Volumes. Der App-Container läuft ohne Root-Rechte und erhält seine Zugangsdaten
erst bei der Initialisierung; sie werden nicht ins Image eingebaut.

Das interne Compose-Netz verwendet `172.30.87.0/24`. Nur aus diesem konfigurierten
Proxy-Netz akzeptiert die App weitergereichte Angaben zum HTTPS-Transport.
Falls das Subnetz mit einem vorhandenen Netz kollidiert, ändern Sie sowohl
`networks.backend.ipam.config.subnet` als auch `--trusted-proxy` zusammen.
Verwenden Sie keine globale Proxy-Freigabe wie `*`.

## Installation in einem Benutzerverzeichnis

Mit Python 3.11 oder neuer und dessen venv-Unterstützung:

```sh
sh packaging/server/install.sh "$HOME/.local/share/threaddesk-server" https://server.example.org
"$HOME/.local/share/threaddesk-server/venv/bin/threaddesk-server" init --data-dir "$HOME/.local/share/threaddesk-server/data" --user alice
```

Das Skript installiert die Anwendung und ihre Server-Abhängigkeiten in eine
eigene virtuelle Umgebung. Ein bestehendes Installationsziel mit venv wird nicht
überschrieben. Es ändert keine globale Python-Installation und startet keinen
Dienst. Prüfen Sie die erzeugte Datei
`~/.local/share/threaddesk-server/threaddesk-server.service`, bevor Sie sie nach
`~/.config/systemd/user/` kopieren und mit `systemctl --user` aktivieren.
Der Dienst bindet ausschließlich `127.0.0.1:8766`. Ein HTTPS-Reverse-Proxy muss
auf diesen Port zeigen und die konfigurierte öffentliche Origin bedienen.
Die mitgelieferte Caddy-Vorlage verwendet für Docker `app:8766`; bei einer
Installation auf dem Host ersetzen Sie dies durch `127.0.0.1:8766`.
Standardmäßig vertraut die App nur dem Proxy auf `127.0.0.1`.

Für eine zeitlich begrenzte lokale Entwicklungsprüfung kann der Server explizit
mit `--allow-http-loopback` und Loopback-Adresse gestartet werden. Das ist keine
Konfiguration für entfernte Browser oder einen öffentlichen Server.

## Projekte und „Auch offline“

Erstellen Sie nach der Anmeldung ein Projekt. Ohne „Auch offline“ speichert der
Server Projektstruktur, Metadaten und Whiteboard, jedoch keine neu übertragenen
Dateiinhalte. Aktivieren Sie die Option gezielt für Projekte, deren Dateien auch
bei ausgeschaltetem Hauptrechner verfügbar sein sollen.

Der lokale Client benötigt eine Projektkennung und einen ausdrücklich gewählten
Projektordner. Er erfasst dessen Dateien erneut bei jedem Abgleich und erkennt
dadurch auch später hinzugefügte Dateien. Ein Zugangstoken gehört in eine private
Datei außerhalb des Projektordners:

```sh
chmod 600 "$HOME/.config/threaddesk-sync.token"
threaddesk-sync --url https://server.example.org --token-file "$HOME/.config/threaddesk-sync.token" --project PROJEKTKENNUNG --root /absoluter/projektordner
```

Mit `--watch --interval 10` versucht der Client den Abgleich regelmäßig erneut,
auch nach einem Verbindungsabbruch. `threaddesk-sync` wird mit den
Server-Abhängigkeiten installiert und kann auf Linux oder macOS laufen.

Der Server zeigt den Sync-Status, fehlende Dateien, benötigte Bytes und Konflikte
an. „Bereit“ setzt einen vollständigen gemeldeten Dateibestand ohne offene
Abhängigkeiten und vollständig übertragene, hashgeprüfte Inhalte voraus.
Ein aktivierter Schalter allein ist kein vollständiger Offline-Stand. Ist der
Hauptrechner ausgeschaltet, stehen nur bereits bestätigte Dateien zur Verfügung;
neue dortige Änderungen können erst nach Wiederverbindung erscheinen.

Die Erkennung ist auf den ausgewählten Projektbaum begrenzt. Symbolische Links,
fehlende Dateien und Verweise aus dem freigegebenen Baum heraus werden nicht
heimlich verfolgt. Gemeldete fehlende oder gesperrte Abhängigkeiten müssen Sie
im Projektbaum verfügbar machen oder ausdrücklich anders zuordnen. Beliebige
Abhängigkeiten fremder Programme, zur Laufzeit geladene Dateien oder externe
Dienste können nicht automatisch vollständig bewiesen werden. Geheimnisdateien
wie `.env`, private Schlüssel und VCS-Interna werden nicht übertragen.

## Versionen, Konflikte und Speicher

Änderungen gehen in beide Richtungen. Der Sync verwendet die zuletzt gemeinsame
Version als Grundlage. Haben beide Seiten dieselbe Datei verändert, bleiben
beide Fassungen erhalten; ein Konflikt muss sichtbar aufgelöst werden. Die
Auswahl einer Fassung ist an den aktuellen Konfliktstand gebunden, damit eine
zwischenzeitlich neu entstandene Version nicht still überschrieben wird.

Ein abgebrochener Transfer wird anhand seines gespeicherten Fortschritts
fortgesetzt. Erst die abschließende Größen- und SHA-256-Prüfung veröffentlicht
eine Version. Wiederholte Bestätigungen erzeugen keine zusätzliche Version.
Versionshistorie und Konfliktkopien benötigen zusätzlichen Speicher. V1 begrenzt
eine Datei auf 64 MiB, einen Transferblock auf 256 KiB und gespeicherte Inhalte
einschließlich Transferreservierungen auf 1 GiB pro Nutzer.

Das ist eine Inhaltsquote. SQLite-Seiten, Journal, Metadaten und lokale
Sicherungskopien benötigen zusätzlichen freien Plattenplatz. Unfertige
Übertragungen lassen sich im Browser abbrechen; dabei werden ausschließlich
unveröffentlichte Teilblöcke und ihre Reservierung freigegeben. Fertige Versionen
bleiben erhalten. Ändert sich eine lokale Datei während eines Teiltransfers,
klärt der Client erst dessen gespeicherten Zustand und beginnt danach neu.

Verdrängte lokale Dateien und zusätzliche Konfliktfassungen liegen im
Projektordner unter `.threaddesk-sync-conflicts/`. Neben jeder Kopie beschreibt
eine private JSON-Datei Originalpfad, Hash und bekannte Version. Dateien dort
nicht ungeprüft entfernen. Die Browser-Auswahl einer Fassung überschreibt keine
noch abweichende lokale Datei; diese muss anschließend bewusst abgeglichen
werden. Veraltete Gerätemeldungen können den Status deshalb bis zum nächsten
erfolgreichen Abgleich auf „geblockt“ halten.

Das Ausschalten von „Auch offline“ verhindert neue Dateiübertragungen. Es löscht
keine bereits gespeicherten Fassungen und niemals Originaldateien auf dem
Hauptrechner. Auch verschwundene Dateien lösen keine automatische Löschkaskade
aus. Eine spätere explizite Speicherbereinigung muss separat entworfen und
freigegeben werden; V1 hat keine automatische Versionslöschung.

## Betrieb und Sicherung

Der Datenordner muss dauerhaft und nur für den Dienstnutzer zugänglich bleiben.
Sichern Sie den gesamten Server-Datenbereich bei angehaltenem Server sowie die
privat verwahrten Zugangsdaten. Eine Kopie einzelner laufender SQLite-Dateien
ist kein zugesagtes konsistentes Backup. Vor Aktualisierungen zuerst sichern,
danach in einem neuen Installationspräfix installieren und den Dienstpfad nach
Prüfung umstellen. Keine Datenverzeichnisse oder Docker-Volumes beim Update
löschen.

Die vorhandene portable Desktop-Sicherung enthält nach Codex 2s geprüftem Stand
`library-files` noch nicht. Dieser neue Serverstand behebt diese separate
Desktop-Sicherungslücke nicht. Produktionsfreigabe benötigt zusätzlich eine
tatsächliche Linux-/TLS-/Wiederherstellungsabnahme und die Integration des
Clients in die gewünschte Desktop-Bedienung.

Der Client gleicht derzeit Projektdateien ab. Bestehende Desktop-Threads,
Aufgaben und Whiteboards werden noch nicht zwischen Desktop und Server
zusammengeführt. Die Browserseite speichert diese Daten bereits mit dem
gemeinsamen ThreadDesk-Kern und schützt Notizänderungen per Revision und
vorheriger Momentaufnahme. Die fehlende Desktop-Metadatenanbindung ist eine
offene Integration, kein vollständig erfüllter Gesamtplan.

Schnittstellen und technische Grenzen:
[server-sync-v1.md](contracts/server-sync-v1.md).
