"""Zweisprachigkeit DE/EN.

Alle Netzwerkpunkt-Werkzeuge sind zweisprachig. Nachruesten ist teuer, also
gehoert jeder sichtbare Text von Anfang an in diesen Katalog und nie direkt
ins Template.

Regeln:
- Schluessel sind stabil, Texte nicht. Ein Schluessel fehlt lieber laut, als
  dass eine Sprache still auf die andere zurueckfaellt.
- Eigennamen werden nicht uebersetzt: ThreadDesk, Gnom-Hub-V1, Grok, Codex,
  Snapshot, Thread, Handoff.
- Der Test tests/test_i18n.py haelt fest, dass beide Sprachen vollstaendig
  sind und dass kein Template deutschen Text hart verdrahtet.
"""

from __future__ import annotations

LANGUAGES = ("de", "en")
DEFAULT_LANGUAGE = "de"

LANGUAGE_NAMES = {"de": "Deutsch", "en": "English"}

CATALOG: dict[str, dict[str, str]] = {
    # --- Grundgeruest ---
    "app.tagline": {
        "de": "Kontext halten · nichts ausführen",
        "en": "Keep context · execute nothing",
    },
    "app.local_note": {
        "de": "Lokal · nichts ausführen",
        "en": "Local · executes nothing",
    },
    "nav.label": {"de": "Ansichten", "en": "Views"},
    "nav.threads": {"de": "Threads", "en": "Threads"},
    "nav.knowledge": {"de": "Wissenspool", "en": "Knowledge"},
    "nav.map": {"de": "Karte", "en": "Map"},
    "nav.language": {"de": "Sprache", "en": "Language"},
    # --- Hilfe ---
    "help.open": {"de": "Tasten", "en": "Keys"},
    "help.title": {"de": "Tastatur", "en": "Keyboard"},
    "help.close": {"de": "Schließen", "en": "Close"},
    "help.new_thread": {"de": "Neuer Thread", "en": "New thread"},
    "help.next_prev": {
        "de": "Nächster / vorheriger Thread",
        "en": "Next / previous thread",
    },
    "help.pick_thread": {"de": "Thread wählen", "en": "Pick thread"},
    "help.snapshot_field": {"de": "Snapshot-Feld", "en": "Snapshot field"},
    "help.microphone": {"de": "Mikrofon an / aus", "en": "Microphone on / off"},
    "help.key_ctrl": {"de": "Strg", "en": "Ctrl"},
    "help.save_form": {"de": "Formular speichern", "en": "Save form"},
    "help.this_help": {"de": "Diese Hilfe", "en": "This help"},
    "help.escape": {"de": "Schließen", "en": "Close"},
    "help.no_agent": {
        "de": "Keine Taste startet einen Agenten.",
        "en": "No key starts an agent.",
    },
    # --- Karte ---
    "map.eyebrow": {
        "de": "Projektgedächtnis · Landkarte",
        "en": "Project memory · map",
    },
    "map.title": {"de": "Zusammenhänge", "en": "Connections"},
    "map.summary_hint": {
        "de": "Die Karte liest ausschließlich den Wissensgraphen.",
        "en": "The map reads the knowledge graph and nothing else.",
    },
    "map.controls": {"de": "Kartensteuerung", "en": "Map controls"},
    "map.effects_on": {"de": "Effekte an", "en": "Effects on"},
    "map.effects_off": {"de": "Effekte aus", "en": "Effects off"},
    "map.zoom_out": {"de": "Herauszoomen", "en": "Zoom out"},
    "map.zoom_in": {"de": "Hineinzoomen", "en": "Zoom in"},
    "map.fit": {"de": "Einpassen", "en": "Fit"},
    "map.stage_label": {"de": "Wissenslandkarte", "en": "Knowledge map"},
    "map.svg_title": {
        "de": "ThreadDesk Wissenslandkarte",
        "en": "ThreadDesk knowledge map",
    },
    "map.svg_desc": {
        "de": (
            "Knoten und ihre gerichteten Beziehungen. Form zeigt den Typ, Farbe "
            "den Zustand. Mit Mausrad zoomen, durch Ziehen verschieben, Knoten "
            "lassen sich versetzen."
        ),
        "en": (
            "Nodes and their directed relations. Shape shows the type, colour the "
            "state. Zoom with the wheel, drag to pan, nodes can be moved."
        ),
    },
    "map.empty": {
        "de": "Noch keine Knoten vorhanden.",
        "en": "No nodes yet.",
    },
    "map.error": {
        "de": "Karte konnte nicht geladen werden.",
        "en": "The map could not be loaded.",
    },
    "map.legend": {"de": "Legende", "en": "Legend"},
    "map.legend_circle": {
        "de": "Projekt · Person · System",
        "en": "Project · person · system",
    },
    "map.legend_rect": {"de": "Aufgabe", "en": "Task"},
    "map.legend_doc": {
        "de": "Entscheidung · Wissen · Ergebnis",
        "en": "Decision · knowledge · result",
    },
    "map.legend_hex": {
        "de": "Werkzeug · Quelle · Ablauf",
        "en": "Tool · source · workflow",
    },
    "map.legend_good": {"de": "bestätigt", "en": "confirmed"},
    "map.legend_wait": {"de": "wartet", "en": "waiting"},
    "map.legend_fresh": {"de": "ungeprüft", "en": "unverified"},
    "map.legend_risk": {"de": "blockiert", "en": "blocked"},
    "map.selection": {"de": "Auswahl", "en": "Selection"},
    "map.no_selection": {"de": "Kein Knoten gewählt", "en": "No node selected"},
    "map.pick_hint": {
        "de": "Klicke einen Knoten an oder wähle ihn mit der Tastatur. Shift sammelt mehrere.",
        "en": "Click a node or pick it with the keyboard. Shift collects several.",
    },
    "map.nodes_relations": {
        "de": "{nodes} Knoten · {relations} Verbindungen",
        "en": "{nodes} nodes · {relations} relations",
    },
    "map.no_details": {"de": "Keine Details", "en": "No details"},
    "map.field_kind": {"de": "Typ", "en": "Type"},
    "map.field_status": {"de": "Status", "en": "Status"},
    "map.field_source": {"de": "Herkunft", "en": "Origin"},
    "map.field_visibility": {"de": "Sichtbarkeit", "en": "Visibility"},
    "map.field_revision": {"de": "Revision", "en": "Revision"},
    # --- Wissenspool ---
    "knowledge.eyebrow": {
        "de": "Projektgedächtnis · Listenansicht",
        "en": "Project memory · list view",
    },
    "knowledge.title": {"de": "Wissenspool", "en": "Knowledge"},
    "knowledge.lead": {
        "de": "Knoten enthalten Wissen. Linien erklären den Zusammenhang.",
        "en": "Nodes hold knowledge. Lines explain how it connects.",
    },
    "knowledge.graph_json": {"de": "Graph-JSON", "en": "Graph JSON"},
    "knowledge.kind": {"de": "Typ", "en": "Type"},
    "knowledge.status": {"de": "Status", "en": "Status"},
    "knowledge.all": {"de": "Alle", "en": "All"},
    "knowledge.filter": {"de": "Filtern", "en": "Filter"},
    "knowledge.reset": {"de": "Zurücksetzen", "en": "Reset"},
    "knowledge.new_node": {"de": "Neuer Knoten", "en": "New node"},
    "knowledge.node_title": {"de": "Titel", "en": "Title"},
    "knowledge.node_title_hint": {
        "de": "Was soll gemerkt werden?",
        "en": "What should be remembered?",
    },
    "knowledge.details": {"de": "Details", "en": "Details"},
    "knowledge.details_hint": {
        "de": "Kurze, bestätigte Beschreibung",
        "en": "Short, confirmed description",
    },
    "knowledge.save_node": {"de": "Knoten speichern", "en": "Save node"},
    "knowledge.new_relation": {"de": "Verbindung anlegen", "en": "Add relation"},
    "knowledge.from": {"de": "Von", "en": "From"},
    "knowledge.relation": {"de": "Verbindung", "en": "Relation"},
    "knowledge.to": {"de": "Zu", "en": "To"},
    "knowledge.save_relation": {"de": "Linie speichern", "en": "Save line"},
    "knowledge.need_two": {
        "de": "Für eine Verbindung werden mindestens zwei Knoten benötigt.",
        "en": "A relation needs at least two nodes.",
    },
    "knowledge.nodes": {"de": "Knoten", "en": "Nodes"},
    "knowledge.relations": {"de": "Verbindungen", "en": "Relations"},
    "knowledge.no_details": {"de": "Keine Details", "en": "No details"},
    "knowledge.next_status_for": {
        "de": "Nächster Status für {title}",
        "en": "Next status for {title}",
    },
    "knowledge.apply": {"de": "Übernehmen", "en": "Apply"},
    "knowledge.empty_nodes": {
        "de": "Noch keine Knoten. Der erste Knoten kann ein Projekt sein.",
        "en": "No nodes yet. The first one can be a project.",
    },
    "knowledge.empty_relations": {
        "de": "Noch keine Verbindungen.",
        "en": "No relations yet.",
    },
    # --- Arbeitsflaeche ---
    "ui.saving": {"de": "Speichere…", "en": "Saving…"},
    # --- Dateien ---
    "files.title": {"de": "Dateien", "en": "Files"},
    "files.hint": {
        "de": "Nur Pfade merken. Kein Upload, kein Öffnen.",
        "en": "Paths only. No upload, no opening.",
    },
    "files.confirm_remove": {"de": "Pfad entfernen?", "en": "Remove path?"},
    "files.remove": {"de": "Weg", "en": "Remove"},
    "files.empty": {"de": "Keine Dateipfade.", "en": "No file paths."},
    "files.add": {"de": "Hinzufügen", "en": "Add"},
    # --- Gate ---
    "gate.title": {"de": "Gate", "en": "Gate"},
    "gate.frozen": {"de": "frozen", "en": "frozen"},
    "gate.open": {"de": "offen", "en": "open"},
    "gate.execute_today": {"de": "Execute heute", "en": "Execute today"},
    "gate.handoff_today": {"de": "Handoff heute", "en": "Handoff today"},
    "gate.cooldown": {"de": "Cooldown", "en": "Cooldown"},
    "gate.confirm_freeze": {
        "de": "Gate einfrieren? Execute- und Handoff-Pakete werden blockiert.",
        "en": "Freeze the gate? Execute and handoff packets will be blocked.",
    },
    "gate.thaw": {"de": "Auftauen", "en": "Thaw"},
    "gate.freeze": {"de": "Einfrieren", "en": "Freeze"},
    "gate.hint": {
        "de": "Sperrt nur Pakete. Startet nichts.",
        "en": "Blocks packets only. Starts nothing.",
    },
    # --- Notizen ---
    "notes.title": {"de": "Notizen", "en": "Notes"},
    "notes.hint": {
        "de": "Mikrofon schreibt nur Text hierher. Startet Grok nicht.",
        "en": "The microphone only writes text here. It does not start Grok.",
    },
    "notes.placeholder": {
        "de": "Kontext, Stand, nächster Schritt",
        "en": "Context, state, next step",
    },
    "notes.append": {
        "de": "Anhängen statt ersetzen",
        "en": "Append instead of replacing",
    },
    "notes.shortcut_hint": {
        "de": "Strg+Enter speichert · m = Mikrofon",
        "en": "Ctrl+Enter saves · m = microphone",
    },
    "notes.mic": {"de": "Mikrofon", "en": "Microphone"},
    "notes.mic_stop": {"de": "Stopp", "en": "Stop"},
    "notes.save": {"de": "Notiz speichern", "en": "Save note"},
    # --- Paket ---
    "packet.title": {"de": "Paket", "en": "Packet"},
    "packet.hint": {
        "de": "Schreibt Dateien. Startet Grok und gnom-hub-v1 nicht.",
        "en": "Writes files. Does not start Grok or gnom-hub-v1.",
    },
    "packet.write_handoff": {"de": "Handoff schreiben", "en": "Write handoff"},
    "packet.gnom": {"de": "Gnom-Brainstorm", "en": "Gnom brainstorm"},
    "packet.grok": {"de": "Grok-Brainstorm", "en": "Grok brainstorm"},
    "packet.not_executed": {"de": "nicht ausgeführt", "en": "not executed"},
    "packet.copy_command": {"de": "Befehl kopieren", "en": "Copy command"},
    "packet.copy_prompt": {"de": "Prompt kopieren", "en": "Copy prompt"},
    # --- Prompt ---
    "prompt.title": {"de": "Prompt", "en": "Prompt"},
    "prompt.hint": {
        "de": "Nur Vorschau. Startet Grok und Gnom nicht.",
        "en": "Preview only. Does not start Grok or Gnom.",
    },
    "prompt.target": {"de": "Ziel", "en": "Target"},
    "prompt.variant": {"de": "Variante", "en": "Variant"},
    "prompt.save_in_thread": {"de": "Im Thread speichern", "en": "Save in thread"},
    "prompt.preview": {"de": "Vorschau", "en": "Preview"},
    "prompt.copy": {"de": "Prompt kopieren", "en": "Copy prompt"},
    "prompt.saved": {"de": "Gespeichert:", "en": "Saved:"},
    # --- Snapshots ---
    "snapshots.title": {"de": "Snapshots", "en": "Snapshots"},
    "snapshots.current": {"de": "Aktuell:", "en": "Current:"},
    "snapshots.none": {"de": "keiner", "en": "none"},
    "snapshots.label_placeholder": {"de": "Label (optional)", "en": "Label (optional)"},
    "snapshots.save": {"de": "Speichern", "en": "Save"},
    "snapshots.unnamed": {"de": "(ohne Label)", "en": "(unnamed)"},
    "snapshots.confirm_restore": {
        "de": "Snapshot laden? Aktuelle Notizen werden überschrieben.",
        "en": "Load snapshot? Current notes will be overwritten.",
    },
    "snapshots.load": {"de": "Laden", "en": "Load"},
    # --- Aktiver Thread ---
    "detail.active_thread": {"de": "Aktiver Thread", "en": "Active thread"},
    "detail.rename": {"de": "Umbenennen", "en": "Rename"},
    "detail.ok": {"de": "OK", "en": "OK"},
    "detail.confirm_archive": {
        "de": "Thread archivieren? Er verschwindet aus der Liste.",
        "en": "Archive thread? It disappears from the list.",
    },
    "detail.archive": {"de": "Archivieren", "en": "Archive"},
    "detail.status": {"de": "Status", "en": "Status"},
    "detail.description": {"de": "Beschreibung", "en": "Description"},
    "detail.description_placeholder": {"de": "Worum geht es?", "en": "What is it about?"},
    "detail.save": {"de": "Speichern", "en": "Save"},
    "detail.no_thread": {"de": "Kein aktiver Thread", "en": "No active thread"},
    "detail.pick": {"de": "Wähle links einen Thread", "en": "Pick a thread on the left"},
    "detail.or_new": {
        "de": "Oder lege einen mit Neu an. Taste n.",
        "en": "Or create one with New. Key n.",
    },
    # --- Threadliste ---
    "list.title": {"de": "Threads", "en": "Threads"},
    "list.new": {"de": "Neu", "en": "New"},
    "list.title_label": {"de": "Titel", "en": "Title"},
    "list.new_thread_placeholder": {"de": "Neuer Thread", "en": "New thread"},
    "list.description": {"de": "Beschreibung", "en": "Description"},
    "list.create": {"de": "Anlegen", "en": "Create"},
    "list.empty": {
        "de": "Keine Threads. Lege oben einen an.",
        "en": "No threads. Create one above.",
    },
}

def normalise(language: str | None) -> str:
    """Gibt immer eine unterstuetzte Sprache zurueck."""
    if not language:
        return DEFAULT_LANGUAGE
    code = language.strip().lower().replace("_", "-").split("-", 1)[0]
    return code if code in LANGUAGES else DEFAULT_LANGUAGE


def from_accept_header(header: str | None) -> str:
    """Liest die erste unterstuetzte Sprache aus einem Accept-Language-Kopf."""
    if not header:
        return DEFAULT_LANGUAGE
    for chunk in header.split(","):
        code = chunk.split(";", 1)[0].strip().lower().replace("_", "-")
        base = code.split("-", 1)[0]
        if base in LANGUAGES:
            return base
    return DEFAULT_LANGUAGE


def translate(key: str, language: str = DEFAULT_LANGUAGE, **values: object) -> str:
    """Uebersetzt einen Schluessel.

    Ein unbekannter Schluessel gibt den Schluessel selbst zurueck, damit die
    Oberflaeche nicht zerbricht — der Test faengt ihn vorher ab.
    """
    entry = CATALOG.get(key)
    if entry is None:
        return key
    text = entry.get(normalise(language)) or entry[DEFAULT_LANGUAGE]
    return text.format(**values) if values else text


def catalog_for(language: str) -> dict[str, str]:
    """Der ganze Katalog in einer Sprache — fuer die Kartenlogik im Browser."""
    code = normalise(language)
    return {key: entry.get(code) or entry[DEFAULT_LANGUAGE]
            for key, entry in CATALOG.items()
}


def normalise(language: str | None) -> str:
    """Gibt immer eine unterstuetzte Sprache zurueck."""
    if not language:
        return DEFAULT_LANGUAGE
    code = language.strip().lower().replace("_", "-").split("-", 1)[0]
    return code if code in LANGUAGES else DEFAULT_LANGUAGE


def from_accept_header(header: str | None) -> str:
    """Liest die erste unterstuetzte Sprache aus einem Accept-Language-Kopf."""
    if not header:
        return DEFAULT_LANGUAGE
    for chunk in header.split(","):
        code = chunk.split(";", 1)[0].strip().lower().replace("_", "-")
        base = code.split("-", 1)[0]
        if base in LANGUAGES:
            return base
    return DEFAULT_LANGUAGE


def translate(key: str, language: str = DEFAULT_LANGUAGE, **values: object) -> str:
    """Uebersetzt einen Schluessel.

    Ein unbekannter Schluessel gibt den Schluessel selbst zurueck, damit die
    Oberflaeche nicht zerbricht — der Test faengt ihn vorher ab.
    """
    entry = CATALOG.get(key)
    if entry is None:
        return key
    text = entry.get(normalise(language)) or entry[DEFAULT_LANGUAGE]
    return text.format(**values) if values else text


def catalog_for(language: str) -> dict[str, str]:
    """Der ganze Katalog in einer Sprache — fuer die Kartenlogik im Browser."""
    code = normalise(language)
    return {key: entry.get(code) or entry[DEFAULT_LANGUAGE]
            for key, entry in CATALOG.items()}
