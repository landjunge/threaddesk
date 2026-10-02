"""One-shot, exact-preimage edits for the current completion branch only."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def patch(name, old, new):
    path = ROOT / name
    text = path.read_text(encoding="utf-8")
    if old not in text:
        if new in text:
            return
        raise RuntimeError("Preimage changed: " + name)
    if text.count(old) != 1:
        raise RuntimeError("Ambiguous preimage: " + name)
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main():
    patch("src/threaddesk/ui/templates/base.html", 'src="https://unpkg.com/htmx.org@2.0.4"', 'src="/static/htmx.min.js"')
    patch("src/threaddesk/ui/templates/base.html", 'src="https://unpkg.com/alpinejs@3.14.8/dist/cdn.min.js"', 'src="/static/alpine.min.js"')
    patch("src/threaddesk/core/i18n.py",
          '    "room.share_entry": {"de": "Für den gewählten Raum", "en": "For the selected room"},',
          '    "room.share_entry": {"de": "Eintrag und Thread-Titel für den Raum freigeben", "en": "Share entry and thread title with the room"},\n'
          '    "room.local_only": {"de": "Nur lesen – neue Einträge bleiben privat", "en": "Read only – new entries stay private"},')
    patch("src/threaddesk/ui/templates/partials/whiteboard.html",
          '<input type="checkbox" name="in_room" value="1" data-room-share />',
          '<input type="checkbox" name="in_room" value="1" data-room-share {% if room.role == "read_only" %}disabled{% endif %} />')
    patch("src/threaddesk/ui/templates/partials/whiteboard.html",
          '<span>{{ t("room.share_entry") }}</span>',
          '<span>{{ t("room.local_only") if room.role == "read_only" else t("room.share_entry") }}</span>')
    patch("src/threaddesk/ui/server.py", '''        if in_room == "1":
            current_room = RoomBook(_svc().store).view().get("current")
            if current_room:
                fields["room_id"] = current_room["id"]
''', '''        if in_room == "1":
            room_view = RoomBook(_svc().store).view()
            current_room = room_view.get("current")
            if not current_room or room_view.get("role") not in {"owner", "member"}:
                page = _room_error(request)
                page.status_code = 403
                return page
            fields["room_id"] = current_room["id"]
''')
    patch("tests/test_room_browser.py", '    page.locator("[data-room-share]").set_checked(shared)',
          '    share = page.locator("[data-room-share]")\n    if shared:\n        share.check()\n    elif share.is_checked():\n        share.uncheck()')
    patch("tests/test_room_browser.py", '''            add_entry(b, thread_a, "Leser darf nicht senden", True)''', '''            expect(b.locator("[data-room-share]")).to_be_disabled()
            rejected = b.request.post(right.url + f"/threads/{thread_a}/whiteboard", form={
                "actor": "Synthetic reader", "actor_type": "human", "entry_type": "note",
                "content": "Verbotene Freigabe", "in_room": "1",
            })
            assert rejected.status == 403
            add_entry(b, thread_a, "Leser darf nicht senden", False)''')
    patch("tests/test_room_browser.py", '''            a, b = context_a.new_page(), context_b.new_page()
            a.goto(left.url)''', '''            external = []
            def local_only(route):
                from urllib.parse import urlparse
                if urlparse(route.request.url).hostname != "127.0.0.1":
                    external.append(route.request.url)
                    route.abort()
                else:
                    route.continue_()
            context_a.route("**/*", local_only)
            context_b.route("**/*", local_only)
            a, b = context_a.new_page(), context_b.new_page()
            a.goto(left.url)''')
    patch("tests/test_room_browser.py", '''            assert left.store().get_thread(thread_a).context.notes == "PRIVAT-NOTIZ-NICHT-TEILEN"''', '''            assert external == [], "The local UI must not request a CDN or another external host"
            assert left.store().get_thread(thread_a).context.notes == "PRIVAT-NOTIZ-NICHT-TEILEN"''')
    patch("tests/test_room_sync_e2e.py", '''        _request(URL_B, f"/threads/{thread_b}/whiteboard", {
            "actor": "Bea", "actor_type": "human", "entry_type": "note",
            "content": "leseraum-von-b", "next_step": "", "in_room": "1",
        })''', '''        with pytest.raises(AssertionError, match="-> 403"):
            _request(URL_B, f"/threads/{thread_b}/whiteboard", {
                "actor": "Bea", "actor_type": "human", "entry_type": "note",
                "content": "leseraum-von-b", "next_step": "", "in_room": "1",
            })''')
    patch("packaging/desktop_entry.py", 'for asset in ("app.js", "map.js", "style.css"):',
          'for asset in ("app.js", "map.js", "style.css", "htmx.min.js", "alpine.min.js"):')
    patch("README.md", '### Heutiger Stand – ehrlich\n', '''### Heutiger Stand – ehrlich

**Abschlussstand vom 2. Oktober 2026:** Dieser Branch ist ein Release-Kandidat,
keine bereits veröffentlichte stabile Ausgabe. Die aktuelle Abnahme und die
zugehörigen Build-Läufe stehen in [PR #62](https://github.com/landjunge/threaddesk/pull/62).
Der Download oben führt zur bisherigen Vorschau; er ist nicht automatisch der
neueste Commit dieses Branches. Neue Pakete tragen einen Herkunftsbeleg mit
Commit-Kennung und Prüfsumme. Ohne geprüften Build kein neuer Release.

''')
    patch("README.md", '| Daten | JSON unter ~/.threaddesk; lokal |',
          '| Daten | Lokal: JSON, optional SQLite; getrennt vom Programmcode |')
    patch("README.md", '| Oberfläche | CLI, lokale Tafel und optionale Weboberfläche |',
          '| Oberfläche | CLI, lokale Weboberfläche und Desktop-Pakete; UI-Bibliotheken werden lokal mitgeliefert |')
    patch("README.md", '### Lokaler Hausmeister / Local caretaker\n', '''### Gemeinsam arbeiten – ausdrücklich freigeben

Im Bereich **Raum** einen Namen eingeben und **Raum anlegen** wählen. Die Leitung
kann eine Einladung als **Mitglied** oder **Nur lesen** erzeugen. Auf der zweiten
Installation den Einladungscode und die lokale Adresse der ersten Installation
eintragen und **Koppeln** wählen. Die eingeblendeten Mitglieder zeigen die Kopplung.

Ein Whiteboard-Eintrag bleibt standardmäßig privat. Nur mit dem Freigabehäkchen
werden **der Eintrag einschließlich seiner Zuordnungen und der Thread-Titel**
für den ausgewählten Raum geteilt. Die separate private Thread-Notiz wird dadurch
nicht freigegeben. **Synchronisieren** stößt den Austausch bewusst an; es gibt
keine heimliche Komplettübertragung des Arbeitsbereichs.

**Nur lesen** darf empfangen, aber keine Raum-Einträge veröffentlichen. Eigene
neue Notizen bleiben privat. Ein Offline-Fehler bedeutet nicht, dass deine Daten
weg sind: Nach Rückkehr der Gegenstelle erneut synchronisieren. Bei einem
Inhaltskonflikt bleiben beide Fassungen erhalten. Wiederholter Sync darf keine
zusätzlichen Kopien erzeugen. Die Desktop-Adresse bleibt nach Neustarts gleich;
ist ihr Port belegt, erscheint ein Fehler statt einer Verbindung zu einer fremden App.

**Aktuelle Grenzen:** Die Abnahme prüft zwei getrennte lokale Serverprozesse, nicht
die Zusammenarbeit über einen Internet-Server. Die Oberfläche ist keine öffentlich
abgesicherte Server-Anwendung und darf nicht unverändert ins Internet gestellt werden.
Der lokale Austausch verwendet HTTP; er ist keine Ende-zu-Ende-Verschlüsselung.
Ein Sync-Paket ist auf 1.000.000 Bytes begrenzt. Zu große oder fehlerhafte Pakete
werden abgewiesen, nicht als erfolgreich abgeschnitten. Externer Server-Sync bleibt
ein eigener, noch abzunehmender Ausbau.

### Lokaler Hausmeister / Local caretaker
''')
    patch("README.md", '**ThreadDesk-macOS.dmg** laden und ThreadDesk nach „Programme“ ziehen — fertig. Die Ausgabe unterstützt Intel-Macs (i7) nativ.',
          '**ThreadDesk-macOS.dmg** für Intel laden und ThreadDesk nach „Programme“ ziehen. Ein Apple-Silicon-Paket ist separat gekennzeichnet. Ein erfolgreicher CI-Build ersetzt nicht den Starttest auf deinem konkreten Mac und seiner macOS-Version.')
    patch("README.md", '**ThreadDesk-Windows.exe** laden und doppelklicken — fertig.',
          '**ThreadDesk-Windows.exe** laden und doppelklicken. Die native Oberfläche benötigt eine funktionierende WebView2-Laufzeit; deren Einrichtung ist nicht durch einen bestandenen Paket-Build bewiesen.')
    print("Applied bounded completion patches; unrelated content preserved")


if __name__ == "__main__":
    main()
