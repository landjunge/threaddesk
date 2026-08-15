from __future__ import annotations

from threaddesk.core.errors import InvalidState
from threaddesk.core.models import Thread

TARGETS = ("grok", "gnom", "generic")
VARIANTS = ("short", "detailed", "steps", "agent")


def generate(thread: Thread, target: str = "grok", variant: str = "detailed") -> str:
    target = target.strip().lower()
    variant = variant.strip().lower()
    if target not in TARGETS:
        raise InvalidState(f"target: {', '.join(TARGETS)}")
    if variant not in VARIANTS:
        raise InvalidState(f"variant: {', '.join(VARIANTS)}")
    body = _body(thread)
    if variant == "short":
        return _short(thread, target, body)
    if variant == "steps":
        return _steps(thread, target, body)
    if variant == "agent":
        return _agent(thread, target, body)
    return _detailed(thread, target, body)


def _body(thread: Thread) -> str:
    files = "\n".join(f"- {p}" for p in thread.context.files) or "- (keine)"
    notes = thread.context.notes.strip() or "(keine)"
    return (
        f"Titel: {thread.title}\n"
        f"Status: {thread.status}\n"
        f"Beschreibung: {thread.description or '(keine)'}\n"
        f"Dateien (Pfade, kein Inhalt):\n{files}\n"
        f"Notizen:\n{notes}"
    )


def _rules(target: str) -> str:
    common = (
        "- Keine Secrets in Antworten wiederholen.\n"
        "- Nichts ausführen, was der Nutzer nicht ausdrücklich will.\n"
        "- Unklarheiten kurz nachfragen statt raten."
    )
    if target == "grok":
        return (
            "Du bist Grok Build. Du änderst nur, was der Auftrag verlangt.\n"
            f"{common}\n"
            "- Brainstorm und Execute trennen. Große Umbauten erst nach Bestätigung.\n"
            "- Tests oder CLI-Check, wenn du Code anfasst."
        )
    if target == "gnom":
        return (
            "Auftrag an gnom-hub-v1. Send = Dialog (Box 2). Execute nur bewusst.\n"
            f"{common}\n"
            "- Send ruft keine Worker auf.\n"
            "- Worker erst nach POST /api/execute, nie von selbst."
        )
    return (
        "Du bist ein präziser Assistent für genau diesen Thread.\n"
        f"{common}"
    )


def _short(thread: Thread, target: str, body: str) -> str:
    return (
        f"{_rules(target)}\n\n"
        f"Aufgabe: Arbeit am Thread „{thread.title}“ fortsetzen.\n"
        f"Stand: {thread.status}.\n"
        f"{thread.context.notes.strip() or thread.description or 'Kein weiterer Kontext.'}\n"
        "Antworte knapp mit dem nächsten sinnvollen Schritt."
    )


def _detailed(thread: Thread, target: str, body: str) -> str:
    return (
        f"{_rules(target)}\n\n"
        "Kontext des Threads (vollständig, lokal gespeichert):\n"
        f"{body}\n\n"
        "Auftrag:\n"
        "1. Fasse den Stand in zwei Sätzen zusammen.\n"
        "2. Nenne die größte offene Lücke.\n"
        "3. Schlage den nächsten konkreten Schritt vor. Noch nicht ausführen,\n"
        "   außer der Nutzer hat Execute ausdrücklich verlangt.\n"
        "Prüfe dich selbst: Ist der Vorschlag im Scope dieses Threads?"
    )


def _steps(thread: Thread, target: str, body: str) -> str:
    return (
        f"{_rules(target)}\n\n"
        f"{body}\n\n"
        "Arbeite schrittweise:\n"
        "Schritt 1: Nur verstehen, nichts ändern.\n"
        "Schritt 2: Plan in höchstens fünf Punkten.\n"
        "Schritt 3: Halt. Warte auf Freigabe, bevor du Dateien anfasst."
    )


def _agent(thread: Thread, target: str, body: str) -> str:
    role = {
        "grok": "Rolle: Grok Build, ein Thread, ein Auftrag.",
        "gnom": "Rolle: Brainstorm-Turn in gnom-hub-v1. Kein Execute.",
        "generic": "Rolle: ein spezialisierter Agent nur für diesen Thread.",
    }[target]
    return (
        f"{role}\n"
        f"{_rules(target)}\n\n"
        f"{body}\n\n"
        "Output-Format:\n"
        "- Stand (1 Satz)\n"
        "- Risiko (1 Satz)\n"
        "- Nächste Aktion (1 Satz, ohne Execute)"
    )
