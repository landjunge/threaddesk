# ThreadDesk Server & Sync

Dieser Entwicklungsstand ergänzt ThreadDesk um einen getrennten Browser-Server
und einen lokalen Sync-Client. Der Server verwendet den gemeinsamen
ThreadDesk-Kern für Projekt-Threads und Whiteboards. Er benötigt keinen Mac und
keine laufende KiraBridge. Der vorhandene Desktop-Server und dessen lokale
Zugriffsregeln bleiben getrennt.

Desktop-Anbindung, Linux-Installation, zertifikatsgeprüftes TLS und vollständige
Wiederherstellung sind im isolierten Abnahmelauf geprüft. Der Linux-Nachweis
verwendet ein frisch gebautes Linux/amd64-Image; der Browsernachweis umfasst
die echte Desktop-Bedienung und den automatischen Abgleich. Das ist keine
Installation auf einem öffentlichen Produktionsserver. Quellstände, Grenzen
und Prüfbelege stehen im [Folgebericht](evidence/codex3-server-sync-followup-20261024/STATUS.md).

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

Für weitere Nutzer zuerst den App-Dienst anhalten, dann initialisieren und
starten. Der Lebenszyklusschutz verweigert Änderungen während des Betriebs:

```sh
docker compose -f packaging/server/compose.yaml stop app
docker compose -f packaging/server/compose.yaml run --rm --no-deps app init --data-dir /data --user bob
docker compose -f packaging/server/compose.yaml up -d app
```

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

Im Desktop den bestehenden Thread öffnen und **Server und Abgleich** wählen.
Server-Adresse, Zugangsschlüssel und lokalen Projektordner eintragen. Ohne
Server-Projektkennung wird ein wiederauffindbarer Eintrag automatisch angelegt;
Wiederholungen nach einer unterbrochenen Antwort erzeugen keinen neuen Eintrag.
Eine bestehende Kennung verbindet beide vorhandenen Stände unter Konfliktschutz.

**Auch offline** stellt geprüfte Kopien bereit. Der automatische Abgleich läuft
während ThreadDesk geöffnet ist und versucht es nach Verbindungsunterbrechung
erneut. **Jetzt abgleichen** ist zusätzlich verfügbar. Notizen, Beschreibung,
Titel, Status, Prompts, zugehörige Projekt-/Aufgabenknoten und Whiteboards gehen
in beide Richtungen. Historische Whiteboard-Einträge bleiben unveränderlich;
die Replikation startet keine Agenten oder Aufgaben.

Zugangsschlüssel liegen ausschließlich im privaten Unterordner
`server-sync-private` des ausgewählten Desktop-Arbeitsbereichs, mit privaten
Dateirechten. Sie werden weder als Thread-Metadaten noch an einen anderen Server
übertragen. Eine neue Server-Adresse benötigt einen neuen expliziten Schlüssel.

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

Die Erkennung erfasst den ganzen Projektbaum bei jedem Durchlauf sowie die
ausdrücklich im lokalen Thread zugeordneten Dateien und Ordner. Weitere erlaubte
Abhängigkeitsordner können im Desktop eingetragen werden. Externe Dateien
bekommen stabile logische Namen unter `_external/`; Änderungen gehen auf den
ursprünglich freigegebenen lokalen Pfad zurück, ohne doppelte Kopie im Hauptbaum.
Die Freigabe einer einzelnen Datei erlaubt keinen Zugriff auf ihre Nachbarn.
Entfernte Quellenfreigaben werden vor jedem Durchlauf erneut geprüft.
Die private Freigabeliste bleibt ausdrücklich von replizierten Dateiverweisen
getrennt. Lokales Hinzufügen/Entfernen im geschützten Desktop-Formular aktualisiert
diese Liste; importierte Metadaten tun das nie. Ältere Verbindungen ohne eigene
Freigabeliste übernehmen keine unbekannten Quellen automatisch. Normale Pfade
bleiben wörtlich, einschließlich Prozentzeichen; nur ausdrückliche `file:`-URIs
werden dekodiert. Beim Wechsel des Projektordners bleibt die Metadatenverbindung
erhalten, während ein eigener Datei-Checkpoint für den neuen Ort angelegt wird.

Unterstützte statische Verweise umfassen Markdown/HTML/CSS, Python-Importe und
literale Dateiöffnungen, JavaScript-/TypeScript-Importe sowie Asset-Manifeste.
Neue Dateien innerhalb freigegebener Ordner werden automatisch erfasst.
Serververweise können niemals zusätzliche lokale Leserechte erzeugen.
Symlinks, fehlende Quellen und nicht auflösbare dynamische Abhängigkeiten
verhindern eine Bereitschaftsbestätigung. Laufzeitgenerierte Namen und fremde
Dienste lassen sich durch statische Analyse nicht vollständig beweisen; sie
müssen als Quellen verfügbar gemacht oder ausdrücklich geklärt werden.
Projektcode wird dafür nicht ausgeführt. `.env`, private Schlüssel, private
Sync-Konfiguration und VCS-Interna werden nicht übertragen; normale Quellmodule
wie `secrets.py` sind keine Schlüsselcontainer allein aufgrund ihres Namens.

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
Wird ein Teiltransfer serverseitig ausdrücklich abgebrochen, verwendet der Client
nach bestätigtem Abbruch eine dauerhaft gespeicherte neue Transferkennung.
Unklare Antworten behalten ihre Kennung; Wiederanlauf erzeugt keine doppelten
fertigen Versionen. Für größere Bestände unterstützt der Manifest-Endpunkt bis
zu 20000 Dateien mit einer eigenen begrenzten Anfragengröße von 96 MiB. Die
Grenzen der Datei-Transferblöcke werden dadurch nicht angehoben.

Verdrängte lokale Dateien und zusätzliche Konfliktfassungen liegen im
jeweiligen Quellordner unter `.threaddesk-sync-conflicts/`. Neben jeder Kopie beschreibt
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
Nach dem Anhalten des Servers eine vollständige Kalt-Sicherung erzeugen:

```sh
threaddesk-server backup --data-dir /privater/server-datenordner --output /privater/sicherungsordner/server.tar
threaddesk-server restore --archive /privater/sicherungsordner/server.tar --data-dir /privater/neuer-server-datenordner
```

Das Ausgabearchiv muss neu sein und außerhalb des Datenordners liegen. Auch der
Restore-Zielordner darf noch nicht existieren; bestehende Daten werden niemals
zusammengeführt oder überschrieben. Für Docker dieselben CLI-Befehle mit dem
angehaltenen Datenvolume in einem Wartungscontainer und einem privaten,
beschreibbaren Sicherungsziel ausführen. Das Quellvolume behalten.

Die Sicherung enthält Zugangskonfiguration, Threads, Notizen-Momentaufnahmen,
Aufgaben, Whiteboards, Dateiversionen, Konfliktjournal, Transferblöcke und Receipts.
Dateihashes, SQLite-Struktur, Versionen und Teiltransfergrenzen werden geprüft.
Restore prüft zuerst vollständig in einem privaten Zwischenordner und
veröffentlicht erst danach das neue Ziel. Ein laufender Server hält eine
Lebenszyklussperre; Backup und zusätzliche Serverstarts werden dann abgewiesen.
ASGI ohne aktivierten Lebenszyklus darf keine API-Anfragen bedienen.

Grenzen: 4 GiB Sicherungsinhalt, 100000 Einträge und 16 MiB Manifest; ein
überschrittener Umfang wird abgewiesen, nie still gekürzt. Ausreichender freier
Platz für Archiv und vollständige Prüf-/Restore-Kopie wird vorab geprüft.
Vor Aktualisierungen zuerst sichern, dann in einem neuen Installationspräfix
installieren und den Dienstpfad nach Prüfung umstellen. Keine Datenverzeichnisse
oder Docker-Volumes beim Update löschen.

Die vorhandene portable Desktop-Sicherung enthält nach Codex 2s geprüftem Stand
`library-files` noch nicht. Dieser neue Serverstand behebt diese separate
Desktop-Sicherungslücke nicht. Die vollständige Server-Sicherung ist davon
unabhängig. Desktop-Zugangsdaten und Sync-Checkpoints liegen im privaten
Arbeitsbereich; die bisherige portable Desktop-Sicherung übernimmt diese
Verbindungskonfiguration nicht automatisch.

Metadatenkonflikte sind sowohl im Desktop als auch im Server-Browser auflösbar.
Jede Auswahl ist an den gelesenen Stand gebunden und erhält vorherige Fassungen
in Momentaufnahmen und Journal. Eine dauerhafte Arbeitsbereichsidentität
verhindert doppelte Aufgaben oder Whiteboard-Einträge nach einem Restore in
einen anderen Ordner. Metadatendokumente sind auf 1 MiB begrenzt; größere Stände
werden mit einem eindeutigen Fehler abgewiesen, nicht abgeschnitten. Der
Datei-CLI kann ohne Desktop verwendet werden; die vorhandenen Desktop-Threads
werden durch die eingerichtete Desktop-Verbindung abgeglichen.

Schnittstellen und technische Grenzen:
[server-sync-v1.md](contracts/server-sync-v1.md).
