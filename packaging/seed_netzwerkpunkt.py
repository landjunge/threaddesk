"""Fill a ThreadDesk workspace with the NetzwerkPunkt suite so the desk is visible."""

from __future__ import annotations

from pathlib import Path

from threaddesk.api.service import ThreadService

HOME = Path.home()
STILLS = HOME / "Desktop" / "NetzwerkPunkt-Video-2026-09-21" / "01-standbilder-phase-a"
LANDINGS = HOME / "netzwerkpunkt" / "landings"

THREADS: tuple[dict, ...] = (
    {
        "title": "NetzwerkPunkt",
        "description": "Hub der Suite. Einzeln stark. Zusammen stärker.",
        "status": "active",
        "notes": (
            "Daniel Filipek / landjunge.\n"
            "Öffentliche Spitze: 4AllPass. Fünf Werkzeuge bleiben getrennt nutzbar.\n"
            "Identität ist nicht Erlaubnis. Senden ist nicht Arbeit starten.\n"
            "Letzte menschliche Entscheidung: Behalten.\n"
            "Hub: https://netzwerkpunkt.de/"
        ),
    },
    {
        "title": "4AllPass",
        "description": "Ein digitaler Tresor, der wirklich dir gehört.",
        "status": "active",
        "notes": (
            "Device-centric ZK-Tresor. FastAPI vergibt keine Tokens.\n"
            "Secrets bleiben im Tresor. ThreadDesk speichert keine Geheimnisse.\n"
            "Repo: /Users/landjunge/4AllPass\n"
            "Seite: https://4allpass.netzwerkpunkt.de/"
        ),
    },
    {
        "title": "TollGate",
        "description": "Prüft, bevor etwas passiert.",
        "status": "active",
        "notes": (
            "Kosten- und Freigabegrenze zwischen Agents und der Außenwelt.\n"
            "Hält keine Secrets. Freigabe bleibt bewusst.\n"
            "Repo: /Users/landjunge/tollgate\n"
            "Seite: https://tollgate.netzwerkpunkt.de/"
        ),
    },
    {
        "title": "gnom-hub-v1",
        "description": "Senden = reden. Arbeit starten = Worker.",
        "status": "active",
        "notes": (
            "Orchestriert freigegebene KI-Arbeit. Startet nichts heimlich.\n"
            "Gnom schreibt Authority-Events, ThreadDesk importiert sie nur.\n"
            "Repo: /Users/landjunge/gnom-hub-v1\n"
            "Seite: https://gnom-hub-v1.netzwerkpunkt.de/"
        ),
    },
    {
        "title": "ThreadDesk",
        "description": "Persistente Threads. Speichert Kontext. Führt nichts aus.",
        "status": "active",
        "notes": (
            "Lokaler Schreibtisch für den gültigen Stand.\n"
            "Visualisiert, führt nicht aus. Kein Agentenstart.\n"
            "Repo: /Users/landjunge/threaddesk\n"
            "Seite: https://threaddesk.netzwerkpunkt.de/"
        ),
    },
    {
        "title": "Agent-X-Files",
        "description": "Singleplayer-Detektivspiel. Akten, nicht Autopilot.",
        "status": "paused",
        "notes": (
            "Öffentliche Landing, Runtime bleibt privat.\n"
            "Seite: https://agent-x-files.netzwerkpunkt.de/"
        ),
    },
    {
        "title": "Workshop",
        "description": "Lernbereich. Kein Software-Produkt der Matrix.",
        "status": "idea",
        "notes": (
            "Konzept und Folien unter netzwerkpunkt/docs/workshop.\n"
            "Live: https://netzwerkpunkt.de/workshop/"
        ),
    },
)

NODES: tuple[tuple[str, str, str, str], ...] = (
    ("project", "NetzwerkPunkt", "active", "Suite-Hub. Einzeln stark. Zusammen stärker."),
    ("tool", "4AllPass", "active", "Digitaler Tresor. Secrets nur dort."),
    ("tool", "TollGate", "active", "Prüft Kosten und Freigabe, bevor etwas passiert."),
    ("tool", "gnom-hub-v1", "active", "Senden ist nicht Arbeit starten."),
    ("tool", "ThreadDesk", "active", "Hält den Stand. Startet keinen Agenten."),
    ("tool", "Agent-X-Files", "paused", "Akten, nicht Autopilot."),
    ("workflow", "Senden ist nicht Arbeit starten", "active", "Gnom: senden = reden, Start = Worker."),
    ("decision", "Identität ist nicht Erlaubnis", "confirmed", "Identity ≠ permission ≠ capability."),
)

RELATIONS: tuple[tuple[str, str, str], ...] = (
    ("NetzwerkPunkt", "contains", "4AllPass"),
    ("NetzwerkPunkt", "contains", "TollGate"),
    ("NetzwerkPunkt", "contains", "gnom-hub-v1"),
    ("NetzwerkPunkt", "contains", "ThreadDesk"),
    ("NetzwerkPunkt", "contains", "Agent-X-Files"),
    ("gnom-hub-v1", "depends_on", "TollGate"),
    ("ThreadDesk", "supports", "gnom-hub-v1"),
    ("TollGate", "related_to", "4AllPass"),
    ("Identität ist nicht Erlaubnis", "supports", "4AllPass"),
    ("Senden ist nicht Arbeit starten", "supports", "gnom-hub-v1"),
)

STILL_FILES = {
    "NetzwerkPunkt": ("01-gesamtsystem.jpg", "07-schluss-vier-kacheln.jpg"),
    "4AllPass": ("05-4allpass-tresor.jpg",),
    "TollGate": ("04-tollgate.jpg",),
    "gnom-hub-v1": ("02-gnom-hub-auftrag.jpg", "03-worker.jpg"),
    "ThreadDesk": ("06-threaddesk.jpg",),
}

LANDING_FILES = {
    "NetzwerkPunkt": HOME / "netzwerkpunkt" / "hub" / "index.html",
    "4AllPass": LANDINGS / "4allpass.html",
    "TollGate": LANDINGS / "tollgate.html",
    "gnom-hub-v1": LANDINGS / "gnom-hub-v1.html",
    "ThreadDesk": LANDINGS / "threaddesk.html",
    "Agent-X-Files": LANDINGS / "agent-x-files.html",
}

REPO_DIRS = {
    "4AllPass": HOME / "4AllPass",
    "TollGate": HOME / "tollgate",
    "gnom-hub-v1": HOME / "gnom-hub-v1",
    "ThreadDesk": HOME / "threaddesk",
    "Workshop": HOME / "netzwerkpunkt" / "docs" / "workshop",
}


def existing(path: Path) -> Path | None:
    return path if path.exists() else None


def discover_files() -> dict[str, list[Path]]:
    found: dict[str, list[Path]] = {}
    for title, names in STILL_FILES.items():
        for name in names:
            path = existing(STILLS / name)
            if path:
                found.setdefault(title, []).append(path)
    for title, path in LANDING_FILES.items():
        live = existing(path)
        if live:
            found.setdefault(title, []).append(live)
    for title, path in REPO_DIRS.items():
        live = existing(path)
        if live:
            found.setdefault(title, []).append(live)
    return found


def seed_workspace(
    svc: ThreadService,
    files: dict[str, list[Path]] | None = None,
) -> dict[str, int]:
    """Create the suite once. Existing titles are left untouched."""
    files = files or {}
    created_threads = 0
    skipped_threads = 0
    by_title = {thread.title: thread for thread in svc.list(include_archived=True)}
    for spec in THREADS:
        if spec["title"] in by_title:
            skipped_threads += 1
            continue
        thread = svc.create(spec["title"], spec["description"])
        svc.set_status(spec["status"], thread.id)
        svc.set_note(spec["notes"], thread.id)
        for path in files.get(spec["title"], []):
            svc.add_file(str(path), thread.id)
        created_threads += 1
        by_title[spec["title"]] = thread

    for spec in reversed(THREADS):
        thread = by_title.get(spec["title"])
        if thread is not None:
            svc.set_status(spec["status"], thread.id)

    created_nodes = 0
    skipped_nodes = 0
    nodes = {node.title: node for node in svc.list_nodes()}
    for kind, title, status, details in NODES:
        if title in nodes:
            skipped_nodes += 1
            continue
        nodes[title] = svc.create_node(kind, title, status=status, details=details)
        created_nodes += 1

    created_relations = 0
    existing_relations = {
        (rel.source_id, rel.kind, rel.target_id) for rel in svc.list_relations()
    }
    for source_title, kind, target_title in RELATIONS:
        source = nodes[source_title]
        target = nodes[target_title]
        key = (source.id, kind, target.id)
        if key in existing_relations:
            continue
        svc.connect(source.id, target.id, kind)
        created_relations += 1
        existing_relations.add(key)

    hub = by_title.get("NetzwerkPunkt")
    if hub is not None:
        svc.switch(hub.id)

    return {
        "created_threads": created_threads,
        "skipped_threads": skipped_threads,
        "created_nodes": created_nodes,
        "skipped_nodes": skipped_nodes,
        "created_relations": created_relations,
    }


def main() -> int:
    svc = ThreadService()
    result = seed_workspace(svc, discover_files())
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
