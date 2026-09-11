"""Billige Wächter gegen Fehler, die man sonst erst im Browser sieht."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

UI = Path(__file__).resolve().parents[1] / "src" / "threaddesk" / "ui"
TEMPLATES = sorted((UI / "templates").glob("*.html"))
CSS = UI / "static" / "polish.css"


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda p: p.name)
def test_templates_have_no_literal_escape_sequences(template: Path) -> None:
    """Ein literales \\n im Markup wird als Text sichtbar."""
    markup = template.read_text(encoding="utf-8")
    assert "\\n" not in markup, f"{template.name} enthält ein literales \\n"


def test_hidden_elements_stay_hidden() -> None:
    """`hidden` muss jede eigene display-Regel schlagen.

    Karte und Wissensliste blenden Overlays über `hidden` aus. Ohne diese
    Regel liegen sie unsichtbar über der Karte und schlucken jeden Klick.
    """
    css = CSS.read_text(encoding="utf-8")
    match = re.search(r"(?<![\w.#:\-\]])\[hidden\]\s*\{([^}]*)\}", css)
    assert match, (
        "polish.css hat keine eigenständige [hidden]-Regel; "
        ".help[hidden] o. ä. zählt nicht"
    )
    rule = match.group(1)
    assert re.search(r"display\s*:\s*none\s*!important", rule), (
        "[hidden] muss display:none !important setzen, sonst gewinnen "
        "eigene display-Regeln wie .map-error{display:grid}"
    )


SHIPPED_PAGES = [
    Path(__file__).resolve().parents[1] / "README.md",
    Path(__file__).resolve().parents[1] / "site" / "index.html",
    Path(__file__).resolve().parents[1] / "installer.html",
]


@pytest.mark.parametrize("page", SHIPPED_PAGES, ids=lambda p: p.name)
def test_public_pages_never_link_to_a_feature_branch(page: Path) -> None:
    """Öffentliche Seiten dürfen nur auf den Standard-Branch verweisen.

    Ein Download-Knopf, der auf `refs/heads/<feature-branch>` zeigt, läuft
    ins Leere, sobald der Branch gemergt und gelöscht ist.
    """
    if not page.exists():
        pytest.skip(f"{page.name} existiert nicht")
    text = page.read_text(encoding="utf-8")
    branches = set(re.findall(r"archive/refs/heads/([^\"'\s>)]+)\.zip", text))
    unexpected = branches - {"main"}
    assert not unexpected, f"{page.name} verlinkt Branch-ZIPs: {sorted(unexpected)}"
