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

# Zwei Sprachebenen, unabhaengig von DE/EN. Klartext ist der Normalfall,
# Fachsprache ist zuschaltbar — nie umgekehrt. Wer die Fachwoerter kennt,
# schaltet sie ein; wer sie nicht kennt, wird nicht damit ueberfahren.
# Vorbild ist 4AllPass (frontend/src/lib/copy-mode.ts).
PLAIN = "plain"
EXPERT = "expert"
REGISTERS = (PLAIN, EXPERT)
DEFAULT_REGISTER = PLAIN
# Ein Fachtext haengt als eigener Eintrag am selben Schluessel. Das Trennzeichen
# ist bewusst kein Punkt: sonst waere "register.expert" die Fachfassung von
# "register" statt ein eigener Schluessel.
EXPERT_SUFFIX = "#expert"

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
    "nav.register": {"de": "Sprachebene", "en": "Wording"},
    "register.plain": {"de": "Klartext", "en": "Plain"},
    "register.expert": {"de": "Fachsprache", "en": "Expert"},
    "register.plain.hint": {
        "de": "Kurze Sätze, keine Fachwörter. So startet ThreadDesk.",
        "en": "Short sentences, no jargon. This is how ThreadDesk starts.",
    },
    "register.expert.hint": {
        "de": "Die Fachbegriffe, wenn du sie kennst.",
        "en": "The technical terms, if you know them.",
    },
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
    # Im Klartext heisst das Ding auf Deutsch Schranke — sonst stuende in der
    # Ueberschrift "Gate" und im Satz darunter "Schranke".
    "gate.title": {"de": "Schranke", "en": "Gate"},
    "gate.title#expert": {"de": "Gate", "en": "Gate"},
    "gate.frozen": {"de": "zu", "en": "closed"},
    "gate.frozen#expert": {"de": "frozen", "en": "frozen"},
    "gate.open": {"de": "offen", "en": "open"},
    "gate.execute_today": {"de": "Heute losgeschickt", "en": "Sent off today"},
    "gate.execute_today#expert": {"de": "Execute heute", "en": "Execute today"},
    "gate.handoff_today": {"de": "Heute übergeben", "en": "Handed over today"},
    "gate.handoff_today#expert": {"de": "Handoff heute", "en": "Handoff today"},
    "gate.cooldown": {"de": "Wartezeit", "en": "Wait time"},
    "gate.cooldown#expert": {"de": "Cooldown", "en": "Cooldown"},
    "gate.confirm_freeze": {
        "de": "Schranke schließen? Dann schreibt ThreadDesk keine Übergabe-Dateien mehr.",
        "en": "Close the gate? ThreadDesk then writes no more handover files.",
    },
    "gate.confirm_freeze#expert": {
        "de": "Gate einfrieren? Execute- und Handoff-Pakete werden blockiert.",
        "en": "Freeze the gate? Execute and handoff packets will be blocked.",
    },
    "gate.thaw": {"de": "Öffnen", "en": "Open"},
    "gate.thaw#expert": {"de": "Auftauen", "en": "Thaw"},
    "gate.freeze": {"de": "Schließen", "en": "Close"},
    "gate.freeze#expert": {"de": "Einfrieren", "en": "Freeze"},
    "gate.hint": {
        "de": "Die Schranke verhindert nur, dass Dateien geschrieben werden. "
              "Sie startet nie etwas.",
        "en": "The gate only stops files from being written. It never starts "
              "anything.",
    },
    "gate.hint#expert": {
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
    "packet.title": {"de": "Übergabe", "en": "Handover"},
    "packet.title#expert": {"de": "Paket", "en": "Packet"},
    "packet.hint": {
        "de": "Legt eine Datei an, die du einem Werkzeug weitergeben kannst. "
              "ThreadDesk startet nichts davon selbst.",
        "en": "Creates a file you can hand to another tool. ThreadDesk starts "
              "none of them itself.",
    },
    "packet.hint#expert": {
        "de": "Schreibt Dateien. Startet Grok und gnom-hub-v1 nicht.",
        "en": "Writes files. Does not start Grok or gnom-hub-v1.",
    },
    "packet.write_handoff": {
        "de": "Übergabe-Datei schreiben", "en": "Write handover file",
    },
    "packet.write_handoff#expert": {
        "de": "Handoff schreiben", "en": "Write handoff",
    },
    "packet.gnom": {"de": "Gnom-Brainstorm", "en": "Gnom brainstorm"},
    "packet.grok": {"de": "Grok-Brainstorm", "en": "Grok brainstorm"},
    "packet.not_executed": {"de": "nicht ausgeführt", "en": "not executed"},
    "packet.copy_command": {"de": "Befehl kopieren", "en": "Copy command"},
    "packet.copy_prompt": {"de": "Prompt kopieren", "en": "Copy prompt"},
    # --- Prompt ---
    "prompt.title": {"de": "Prompt", "en": "Prompt"},
    "prompt.hint": {
        "de": "Der fertige Text zum Kopieren. ThreadDesk schickt ihn nirgendwo hin.",
        "en": "The finished text, ready to copy. ThreadDesk sends it nowhere.",
    },
    "prompt.hint#expert": {
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
    "snapshots.title": {"de": "Zwischenstände", "en": "Saved states"},
    "snapshots.title#expert": {"de": "Snapshots", "en": "Snapshots"},
    "snapshots.hint": {
        "de": "Friert die Notizen von jetzt ein. Du kannst sie später "
              "zurückholen.",
        "en": "Freezes the notes as they are now. You can bring them back later.",
    },
    "snapshots.hint#expert": {
        "de": "Legt eine Kopie der Notizen ab, ladbar per Snapshot-ID.",
        "en": "Stores a copy of the notes, loadable by snapshot id.",
    },
    "snapshots.current": {"de": "Aktuell:", "en": "Current:"},
    "snapshots.none": {"de": "keiner", "en": "none"},
    "snapshots.label_placeholder": {"de": "Label (optional)", "en": "Label (optional)"},
    "snapshots.save": {"de": "Speichern", "en": "Save"},
    "snapshots.unnamed": {"de": "(ohne Label)", "en": "(unnamed)"},
    "snapshots.confirm_restore": {
        "de": "Zwischenstand zurückholen? Was jetzt in den Notizen steht, "
              "geht dabei verloren.",
        "en": "Bring this state back? Whatever is in the notes now will be lost.",
    },
    "snapshots.confirm_restore#expert": {
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
    # --- Knotenarten (Auswahlmenues) ---
    "kind.project": {
        "de": "Projekt",
        "en": "Project",
    },
    "kind.decision": {
        "de": "Entscheidung",
        "en": "Decision",
    },
    "kind.task": {
        "de": "Aufgabe",
        "en": "Task",
    },
    "kind.result": {
        "de": "Ergebnis",
        "en": "Result",
    },
    "kind.person": {
        "de": "Person",
        "en": "Person",
    },
    "kind.agent": {
        "de": "Agent",
        "en": "Agent",
    },
    "kind.document": {
        "de": "Dokument",
        "en": "Document",
    },
    "kind.tool": {
        "de": "Werkzeug",
        "en": "Tool",
    },
    "kind.source": {
        "de": "Quelle",
        "en": "Source",
    },
    "kind.workflow": {
        "de": "Ablauf",
        "en": "Workflow",
    },
    # --- Knotenzustände (Auswahlmenues) ---
    "status.idea": {
        "de": "Idee",
        "en": "Idea",
    },
    "status.candidate": {
        "de": "Kandidat",
        "en": "Candidate",
    },
    "status.proposed": {
        "de": "Vorgeschlagen",
        "en": "Proposed",
    },
    "status.confirmed": {
        "de": "Bestätigt",
        "en": "Confirmed",
    },
    "status.active": {
        "de": "Aktiv",
        "en": "Active",
    },
    "status.ready": {
        "de": "Bereit",
        "en": "Ready",
    },
    "status.assigned": {
        "de": "Zugewiesen",
        "en": "Assigned",
    },
    "status.in_progress": {
        "de": "In Arbeit",
        "en": "In progress",
    },
    "status.waiting": {
        "de": "Wartet",
        "en": "Waiting",
    },
    "status.blocked": {
        "de": "Blockiert",
        "en": "Blocked",
    },
    "status.delivered": {
        "de": "Geliefert",
        "en": "Delivered",
    },
    "status.review": {
        "de": "Prüfung",
        "en": "Review",
    },
    "status.unverified": {
        "de": "Ungeprüft",
        "en": "Unverified",
    },
    "status.verified": {
        "de": "Geprüft",
        "en": "Verified",
    },
    "status.accepted": {
        "de": "Angenommen",
        "en": "Accepted",
    },
    "status.rejected": {
        "de": "Abgelehnt",
        "en": "Rejected",
    },
    "status.rework": {
        "de": "Nacharbeit",
        "en": "Rework",
    },
    "status.superseded": {
        "de": "Ersetzt",
        "en": "Superseded",
    },
    "status.done": {
        "de": "Fertig",
        "en": "Done",
    },
    "status.paused": {
        "de": "Pausiert",
        "en": "Paused",
    },
    "status.archived": {
        "de": "Archiviert",
        "en": "Archived",
    },
    # --- Beziehungsarten (Auswahlmenues) ---
    "relation.contains": {
        "de": "enthält",
        "en": "contains",
    },
    "relation.depends_on": {
        "de": "hängt ab von",
        "en": "depends on",
    },
    "relation.assigned_to": {
        "de": "zugewiesen an",
        "en": "assigned to",
    },
    "relation.produced": {
        "de": "erzeugte",
        "en": "produced",
    },
    "relation.supports": {
        "de": "stützt",
        "en": "supports",
    },
    "relation.references": {
        "de": "verweist auf",
        "en": "references",
    },
    "relation.blocks": {
        "de": "blockiert",
        "en": "blocks",
    },
    "relation.follows": {
        "de": "folgt auf",
        "en": "follows",
    },
    "relation.related_to": {
        "de": "verwandt mit",
        "en": "related to",
    },
    # --- Prompt-Ziele (Auswahlmenues) ---
    "prompt.target.gnom": {
        "de": "Gnom-Hub-V1",
        "en": "Gnom-Hub-V1",
    },
    "prompt.target.grok": {
        "de": "Grok",
        "en": "Grok",
    },
    "prompt.target.generic": {
        "de": "Allgemein",
        "en": "Generic",
    },
    # --- Prompt-Varianten (Auswahlmenues) ---
    "prompt.variant.detailed": {
        "de": "Ausführlich",
        "en": "Detailed",
    },
    "prompt.variant.short": {
        "de": "Kurz",
        "en": "Short",
    },
    "prompt.variant.steps": {
        "de": "Schritte",
        "en": "Steps",
    },
    "prompt.variant.agent": {
        "de": "Agent",
        "en": "Agent",
    },
    # --- Kommandozeile: Ausgaben ---
    "cli.description": {
        "de": "ThreadDesk — Kontext halten, nichts ausführen.",
        "en": "ThreadDesk — keep context, execute nothing.",
    },
    "cli.error": {"de": "fehler: {message}", "en": "error: {message}"},
    "cli.field.description": {"de": "beschreibung: {value}", "en": "description: {value}"},
    "cli.field.status": {
        "de": "status: {status}  snap: {snapshot}",
        "en": "status: {status}  snap: {snapshot}",
    },
    "cli.section.files": {"de": "--- dateien ---", "en": "--- files ---"},
    "cli.section.notes": {"de": "--- notizen ---", "en": "--- notes ---"},
    "cli.notes.empty": {"de": "(leer)", "en": "(empty)"},
    "cli.thread.created": {
        "de": "angelegt und aktiv: {id}  {title}",
        "en": "created and active: {id}  {title}",
    },
    "cli.thread.none": {"de": "keine threads", "en": "no threads"},
    "cli.thread.active": {"de": "aktiv: {id}  {title}", "en": "active: {id}  {title}"},
    "cli.thread.no_active": {"de": "kein aktiver thread", "en": "no active thread"},
    "cli.thread.renamed": {
        "de": "umbenannt: {id}  {title}",
        "en": "renamed: {id}  {title}",
    },
    "cli.thread.archived": {"de": "archiviert: {id}", "en": "archived: {id}"},
    "cli.thread.unarchived": {
        "de": "wieder offen (paused): {id}",
        "en": "reopened (paused): {id}",
    },
    "cli.thread.deleted": {"de": "gelöscht: {id}", "en": "deleted: {id}"},
    "cli.thread.delete_guard": {
        "de": "löschen nur mit --yes (vorher td archive)",
        "en": "delete requires --yes (run td archive first)",
    },
    "cli.note.saved": {"de": "notiz gesetzt: {id}", "en": "note saved: {id}"},
    "cli.description.saved": {
        "de": "beschreibung gesetzt: {id}",
        "en": "description saved: {id}",
    },
    "cli.status.saved": {"de": "status {status}: {id}", "en": "status {status}: {id}"},
    "cli.files.none": {"de": "keine dateien", "en": "no files"},
    "cli.files.added": {"de": "datei: {path}  ({id})", "en": "file: {path}  ({id})"},
    "cli.files.removed": {
        "de": "entfernt: {path}  ({id})",
        "en": "removed: {path}  ({id})",
    },
    "cli.snap.saved": {
        "de": "zwischenstand gespeichert: {id}  {label}",
        "en": "state saved: {id}  {label}",
    },
    "cli.snap.saved#expert": {
        "de": "snapshot: {id}  {label}", "en": "snapshot: {id}  {label}",
    },
    "cli.snap.no_label": {"de": "(ohne name)", "en": "(no name)"},
    "cli.snap.no_label#expert": {"de": "(ohne label)", "en": "(no label)"},
    "cli.snap.none": {
        "de": "keine zwischenstände", "en": "no saved states",
    },
    "cli.snap.none#expert": {"de": "keine snapshots", "en": "no snapshots"},
    "cli.snap.restored": {
        "de": "zurückgeholt: {id}  stand={snapshot}",
        "en": "brought back: {id}  state={snapshot}",
    },
    "cli.snap.restored#expert": {
        "de": "wiederhergestellt: {id}  snap={snapshot}",
        "en": "restored: {id}  snap={snapshot}",
    },
    "cli.prompt.none": {
        "de": "kein text im thread gespeichert",
        "en": "no text stored in the thread",
    },
    "cli.prompt.none#expert": {
        "de": "keine gespeicherten prompts",
        "en": "no stored prompts",
    },
    "cli.prompt.stored": {
        "de": "--- im thread gespeichert ---",
        "en": "--- stored in thread ---",
    },
    "cli.packet.grok": {
        "de": "datei geschrieben: {path}  (grok wurde nicht gestartet)",
        "en": "file written: {path}  (grok was not started)",
    },
    "cli.packet.grok#expert": {
        "de": "paket: {path}  (grok nicht gestartet)",
        "en": "packet: {path}  (grok not started)",
    },
    "cli.packet.gnom": {
        "de": "datei geschrieben: {path}  (gnom wurde nicht gestartet, "
              "nichts gesendet)",
        "en": "file written: {path}  (gnom was not started, nothing sent)",
    },
    "cli.packet.gnom#expert": {
        "de": "paket: {path}  (gnom nicht gestartet, nichts gesendet)",
        "en": "packet: {path}  (gnom not started, nothing sent)",
    },
    "cli.gate.frozen": {
        "de": "geschlossen: {frozen}  tag: {day}",
        "en": "closed: {frozen}  day: {day}",
    },
    "cli.gate.frozen#expert": {
        "de": "frozen: {frozen}  tag: {day}",
        "en": "frozen: {frozen}  day: {day}",
    },
    "cli.gate.yes": {"de": "ja", "en": "yes"},
    "cli.gate.no": {"de": "nein", "en": "no"},
    "cli.gate.execute_today": {
        "de": "heute losgeschickt: {used}/{limit}  pro thread: {per_thread}",
        "en": "sent off today: {used}/{limit}  per thread: {per_thread}",
    },
    "cli.gate.execute_today#expert": {
        "de": "execute heute: {used}/{limit}  pro thread: {per_thread}",
        "en": "execute today: {used}/{limit}  per thread: {per_thread}",
    },
    "cli.gate.handoff_today": {
        "de": "heute übergeben: {used}/{limit}  pro thread: {per_thread}",
        "en": "handed over today: {used}/{limit}  per thread: {per_thread}",
    },
    "cli.gate.handoff_today#expert": {
        "de": "handoff heute: {used}/{limit}  pro thread: {per_thread}",
        "en": "handoff today: {used}/{limit}  per thread: {per_thread}",
    },
    "cli.gate.cooldown": {
        "de": "wartezeit: {seconds}s", "en": "wait time: {seconds}s",
    },
    "cli.gate.cooldown#expert": {
        "de": "cooldown: {seconds}s", "en": "cooldown: {seconds}s",
    },
    "cli.gate.last": {
        "de": "zuletzt: {action}  {thread}  {at}",
        "en": "last: {action}  {thread}  {at}",
    },
    "cli.gate.allow": {"de": "ok  {action}", "en": "ok  {action}"},
    "cli.gate.block": {
        "de": "gestoppt  {action}", "en": "stopped  {action}",
    },
    "cli.gate.block#expert": {
        "de": "block  {action}", "en": "block  {action}",
    },
    "cli.gate.remaining": {
        "de": "übrig  thread={thread}  tag={day}",
        "en": "left  thread={thread}  day={day}",
    },
    "cli.gate.remaining#expert": {
        "de": "rest thread={thread}  tag={day}",
        "en": "remaining thread={thread}  day={day}",
    },
    "cli.dash.html": {"de": "html: {path}", "en": "html: {path}"},
    "cli.dash.opened": {
        "de": "browser geöffnet (keine Agenten)",
        "en": "browser opened (no agents)",
    },
    "cli.serve.missing": {
        "de": "fehlende Abhängigkeit: pip install -e \".[ui]\"",
        "en": "missing dependency: pip install -e \".[ui]\"",
    },
    "cli.serve.running": {
        "de": "ThreadDesk UI  http://{host}:{port}  (führt nichts aus)",
        "en": "ThreadDesk UI  http://{host}:{port}  (executes nothing)",
    },
    # --- Kommandozeile: Hilfetexte ---
    "cli.help.lang": {
        "de": "Ausgabesprache: de oder en",
        "en": "Output language: de or en",
    },
    "cli.help.mode": {
        "de": "Sprachebene: plain (Klartext, Standard) oder expert (Fachsprache)",
        "en": "Wording: plain (default) or expert (technical terms)",
    },
    "cli.help.new": {
        "de": "Thread anlegen und aktivieren",
        "en": "Create and activate a thread",
    },
    "cli.help.list": {"de": "Threads listen", "en": "List threads"},
    "cli.help.include_archived": {
        "de": "inkl. archivierte",
        "en": "include archived",
    },
    "cli.help.switch": {
        "de": "Thread aktivieren (id, Nummer oder Titel)",
        "en": "Activate a thread (id, number or title)",
    },
    "cli.help.switch_id": {
        "de": "ohne Argument: Liste",
        "en": "without argument: list",
    },
    "cli.help.current": {
        "de": "Aktiven Thread inkl. Kontext zeigen",
        "en": "Show the active thread and its context",
    },
    "cli.help.note": {
        "de": "Notiz setzen (überschreibt, außer -a)",
        "en": "Set the note (overwrites unless -a)",
    },
    "cli.help.describe": {"de": "Beschreibung setzen", "en": "Set the description"},
    "cli.help.status": {
        "de": "idea | active | paused | done",
        "en": "idea | active | paused | done",
    },
    "cli.help.files": {
        "de": "Dateipfade im Kontext (kein Inhalt)",
        "en": "File paths in the context (no content)",
    },
    "cli.help.rename": {"de": "Thread umbenennen", "en": "Rename a thread"},
    "cli.help.archive": {"de": "Thread archivieren", "en": "Archive a thread"},
    "cli.help.unarchive": {
        "de": "Archiv holen (wird paused)",
        "en": "Bring back from archive (becomes paused)",
    },
    "cli.help.delete": {
        "de": "Archivierten Thread löschen",
        "en": "Delete an archived thread",
    },
    "cli.help.snap": {"de": "Zwischenstände", "en": "Saved states"},
    "cli.help.snap#expert": {"de": "Snapshots", "en": "Snapshots"},
    "cli.help.snap_save": {
        "de": "Notizen von jetzt festhalten", "en": "Keep the notes as they are now",
    },
    "cli.help.snap_save#expert": {
        "de": "Snapshot speichern", "en": "Save a snapshot",
    },
    "cli.help.snap_list": {
        "de": "Zwischenstände listen", "en": "List saved states",
    },
    "cli.help.snap_list#expert": {
        "de": "Snapshots listen", "en": "List snapshots",
    },
    "cli.help.snap_load": {
        "de": "Zwischenstand zurückholen (überschreibt die Notizen)",
        "en": "Bring a saved state back (overwrites the notes)",
    },
    "cli.help.snap_load#expert": {
        "de": "Snapshot laden", "en": "Load a snapshot",
    },
    "cli.help.prompt": {
        "de": "Text zum Kopieren aus dem Thread bauen (schickt ihn nirgendwo hin)",
        "en": "Build text to copy from the thread (sends it nowhere)",
    },
    "cli.help.prompt#expert": {
        "de": "Prompt aus Thread-Kontext bauen (führt nichts aus)",
        "en": "Build a prompt from the thread context (executes nothing)",
    },
    "cli.help.prompt_save": {"de": "im Thread speichern", "en": "store in the thread"},
    "cli.help.handoff": {
        "de": "Übergabe-Datei für Gnom-Hub schreiben (startet nichts)",
        "en": "Write a handover file for Gnom-Hub (starts nothing)",
    },
    "cli.help.handoff#expert": {
        "de": "Lokales Handoff-JSON für Gnom-Hub (startet nichts)",
        "en": "Local handoff JSON for Gnom-Hub (starts nothing)",
    },
    "cli.help.mcp": {
        "de": "MCP-Server auf stdin/stdout (nur Thread-Daten)",
        "en": "MCP server on stdin/stdout (thread data only)",
    },
    "cli.help.grok": {
        "de": "Grok-Build-Paket schreiben (startet Grok nicht)",
        "en": "Write a Grok build packet (does not start Grok)",
    },
    "cli.help.grok_execute": {
        "de": "Execute-Paket, immer noch kein Start",
        "en": "Execute packet, still no start",
    },
    "cli.help.gnom": {
        "de": "gnom-hub-v1-Paket schreiben (startet und sendet nichts)",
        "en": "Write a gnom-hub-v1 packet (starts nothing, sends nothing)",
    },
    "cli.help.gnom_execute": {
        "de": "chat + /api/execute, immer noch kein POST",
        "en": "chat + /api/execute, still no POST",
    },
    "cli.help.gate": {
        "de": "Schranke: begrenzt Schleifen und Tagesmenge (startet kein Tollgate)",
        "en": "Gate: limits loops and the daily amount (does not start Tollgate)",
    },
    "cli.help.gate#expert": {
        "de": "Lokaler Loop-/Tages-Schutz (kein Tollgate-Start)",
        "en": "Local loop and daily guard (does not start Tollgate)",
    },
    "cli.help.dash": {
        "de": "Nur-Lese-Tafel (HTML + Terminal, kein Server)",
        "en": "Read-only board (HTML + terminal, no server)",
    },
    "cli.help.dash_open": {"de": "HTML lokal öffnen", "en": "Open the HTML locally"},
    "cli.help.graph": {
        "de": "Knoten und Verbindungen als JSON ausgeben",
        "en": "Print nodes and relations as JSON",
    },
    "cli.help.serve": {
        "de": "Lokale UI auf localhost (führt nichts aus)",
        "en": "Local UI on localhost (executes nothing)",
    },
    "cli.help.serve_open": {"de": "Browser öffnen", "en": "Open the browser"},
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


# Reihenfolge fuer die Kommandozeile: unsere eigene Variable schlaegt die
# Locale des Systems. "C" und "POSIX" heissen "keine Vorliebe" und werden
# uebersprungen, sonst wuerde jede Server-Shell stumm auf Deutsch landen.
ENVIRONMENT_VARIABLES = ("THREADDESK_LANG", "LC_ALL", "LC_MESSAGES", "LANG")
NEUTRAL_LOCALES = {"c", "posix", ""}


# Eigene Variable fuer die Sprachebene. Es gibt keine Locale dafuer, also
# gibt es auch nichts vom System zu erben.
REGISTER_VARIABLE = "THREADDESK_MODE"


def register_from_environment(env: dict[str, str] | None = None) -> str:
    """Liest die Sprachebene aus der Umgebung. Ohne Angabe: Klartext."""
    import os

    source = os.environ if env is None else env
    return normalise_register(source.get(REGISTER_VARIABLE))


def from_environment(env: dict[str, str] | None = None) -> str:
    """Liest die Sprache aus den ueblichen Locale-Variablen."""
    import os

    source = os.environ if env is None else env
    for name in ENVIRONMENT_VARIABLES:
        raw = (source.get(name) or "").strip()
        code = raw.split(".", 1)[0].split("@", 1)[0]
        if code.lower() in NEUTRAL_LOCALES:
            continue
        return normalise(code)
    return DEFAULT_LANGUAGE


def normalise_register(register: str | None) -> str:
    """Gibt immer eine unterstuetzte Sprachebene zurueck."""
    if not register:
        return DEFAULT_REGISTER
    value = register.strip().lower()
    return value if value in REGISTERS else DEFAULT_REGISTER


def _entry(key: str, register: str) -> dict[str, str] | None:
    """Der Eintrag fuer diesen Schluessel auf dieser Ebene.

    Auf der Fachebene zaehlt die Variante `<schluessel>.expert`, wenn es sie
    gibt. Gibt es sie nicht, bleibt der Klartext stehen — die meisten Texte
    brauchen keine zweite Fassung, und einen erfundenen Fachbegriff
    hinzuschreiben waere schlechter als der klare Satz.
    """
    if normalise_register(register) == EXPERT:
        variant = CATALOG.get(key + EXPERT_SUFFIX)
        if variant is not None:
            return variant
    return CATALOG.get(key)


def translate(key: str, language: str = DEFAULT_LANGUAGE,
              register: str = DEFAULT_REGISTER, **values: object) -> str:
    """Uebersetzt einen Schluessel.

    Ein unbekannter Schluessel gibt den Schluessel selbst zurueck, damit die
    Oberflaeche nicht zerbricht — der Test faengt ihn vorher ab.
    """
    entry = _entry(key, register)
    if entry is None:
        return key
    text = entry.get(normalise(language)) or entry[DEFAULT_LANGUAGE]
    return text.format(**values) if values else text


def catalog_for(language: str, register: str = DEFAULT_REGISTER) -> dict[str, str]:
    """Der ganze Katalog in einer Sprache — fuer die Kartenlogik im Browser.

    Die `.expert`-Varianten tauchen nicht als eigene Schluessel auf; sie sind
    bereits eingesetzt, wo die Fachebene gewaehlt ist.
    """
    code = normalise(language)
    keys = (key for key in CATALOG if not key.endswith(EXPERT_SUFFIX))
    return {key: (_entry(key, register) or CATALOG[key]).get(code)
                 or CATALOG[key][DEFAULT_LANGUAGE]
            for key in keys}
