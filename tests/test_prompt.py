from pathlib import Path

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.core.errors import InvalidState
from threaddesk.storage.json_store import JsonStore


@pytest.fixture
def svc(tmp_path: Path) -> ThreadService:
    return ThreadService(store=JsonStore(tmp_path))


def test_prompt_contains_thread_and_does_not_execute(svc: ThreadService) -> None:
    svc.create("Tollgate Härten", "Protect vor dem Call")
    svc.set_note("E2E-015 noch offen")
    svc.add_file("FAILURES.md")
    text = svc.prompt(target="grok", variant="detailed")
    assert "Tollgate Härten" in text
    assert "E2E-015" in text
    assert "FAILURES.md" in text
    assert "Execute" in text
    assert "Nichts ausführen" in text or "nicht ausführen" in text.lower()


def test_prompt_save_and_variants(svc: ThreadService) -> None:
    svc.create("Gnom Desk")
    short = svc.prompt(target="gnom", variant="short", save=True)
    assert "@bs" in short
    assert svc.prompts()
    agent = svc.prompt(target="generic", variant="agent")
    assert "Nächste Aktion" in agent
    with pytest.raises(InvalidState):
        svc.prompt(target="openai")
