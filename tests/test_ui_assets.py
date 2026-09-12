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


# ------------------------------------------------------- Ein Design, nicht zehn

STYLESHEETS = sorted((Path(__file__).resolve().parents[1]
                      / "src" / "threaddesk" / "ui" / "static").glob("*.css"))

FONT_SIZE = re.compile(r"font-size:\s*([^;]+);|font:\s*[^;]*?(\d[\d.]*(?:px|rem|em))")
RADIUS = re.compile(r"border-radius:\s*([^;]+);")
# Ausnahmen gelten fuer eine STELLE, nicht fuer einen Wert. Sonst erlaubt
# "999px ist ok" jedem Knopf, wieder rund zu werden — genau das ist beim
# Schreiben dieses Tests passiert und erst durch die Probe aufgefallen.
SHAPE_EXCEPTIONS = {
    ".node-shape": "Kreis statt Ecke: die Form bedeutet auf der Karte die Knotenart.",
    ".map-legend .key-circle": "Zeigt dieselbe Kartenform in der Legende.",
    ".map-legend .key-tone": "Zeigt dieselbe Kartenform in der Legende.",
}


# Kommentare erst schwaerzen, Laenge erhalten, damit Zeilennummern stimmen.
COMMENT = re.compile(r"/\*.*?\*/", re.S)


def _declarations(pattern):
    """Jede Deklaration mit Datei, Zeile, Wert — und dem Selektor, zu dem sie gehört."""
    found = []
    for sheet in STYLESHEETS:
        text = COMMENT.sub(lambda m: re.sub(r"\S", " ", m.group(0)),
                           sheet.read_text(encoding="utf-8"))
        for match in pattern.finditer(text):
            value = (match.group(1) or (match.lastindex and match.group(match.lastindex)) or "")
            value = value.strip()
            if not value:
                continue
            opening = text.rfind("{", 0, match.start())
            start = text.rfind("}", 0, opening) + 1
            selector = " ".join(text[start:opening].split())
            found.append((sheet.name, text[:match.start()].count("\n") + 1,
                          value, selector))
    return found


def test_at_most_four_font_sizes() -> None:
    """Höchstens vier Schriftgrößen.

    Vorher standen Tokens neben 16px, 0.82em, 0.72rem und 0.68rem — drei
    Einheiten durcheinander. Das sah aus wie hundert Größen.
    """
    allowed = {"var(--text-sm)", "var(--text-base)", "var(--text-lg)",
               "var(--text-xl)"}
    offenders = [f"{sheet}:{line}: {value}  ({selector})"
                 for sheet, line, value, selector in _declarations(FONT_SIZE)
                 if value not in allowed]
    assert not offenders, (
        "Schriftgröße außerhalb der vier Tokens:\n" + "\n".join(offenders))


def test_at_most_four_font_tokens_are_defined() -> None:
    """Was es nicht gibt, kann niemand benutzen."""
    text = (STYLESHEETS[0].parent / "style.css").read_text(encoding="utf-8")
    defined = set(re.findall(r"--text-[\w-]+(?=:)", text))
    assert len(defined) <= 4, defined


def test_controls_are_square_and_surfaces_share_one_radius() -> None:
    """Eckige Bedienelemente, eine Rundung für Flächen.

    Vorher: acht verschiedene Rundungen, eckige neben runden Knöpfen.
    """
    offenders = [f"{sheet}:{line}: {selector} → {value}"
                 for sheet, line, value, selector in _declarations(RADIUS)
                 if value != "0"
                 and selector not in SHAPE_EXCEPTIONS]
    assert not offenders, (
        "Keine Rundungen. Eine andere Form braucht einen Eintrag in "
        "SHAPE_EXCEPTIONS mit Grund:\n"
        + "\n".join(offenders))


def test_every_shape_exception_carries_a_reason() -> None:
    for selector, reason in SHAPE_EXCEPTIONS.items():
        assert len(reason.strip()) > 15, f"{selector} ohne Begründung"


def test_no_radius_token_exists() -> None:
    """Keine Rundungen — also auch kein Token dafür."""
    text = (STYLESHEETS[0].parent / "style.css").read_text(encoding="utf-8")
    assert not re.findall(r"--radius-[\w-]+(?=:)", text)


def test_dropdowns_do_not_use_the_operating_system_widget() -> None:
    """Ohne appearance:none zeichnet das System das Menü selbst.

    Genau das war der gemeldete 3D-Effekt: unter Windows ein fremder Rahmen,
    fremde Schrift, fremder Pfeil — mitten in der eigenen Oberfläche.
    """
    # Kommentare erst entfernen — dieser Test hat sonst den eigenen
    # Erklaertext gelesen ("Ohne appearance:none ...") und war damit blind.
    text = COMMENT.sub(" ", (STYLESHEETS[0].parent / "polish.css")
                       .read_text(encoding="utf-8"))
    block = text[text.index("\nselect {"):]
    block = block[:block.index("}")]
    # Nicht per Teilzeichenkette pruefen: "-webkit-appearance: none" enthaelt
    # "appearance: none". Diese Falle ist beim Schreiben zugeschnappt.
    assert re.search(r"(?<![\w-])appearance:\s*none", block), \
        "select übernimmt die System-Darstellung"
    assert "-webkit-appearance: none" in block, "Safari und Chrome brauchen das Präfix"
