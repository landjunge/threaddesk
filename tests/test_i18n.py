"""Zweisprachigkeit DE/EN — und der Wächter dagegen, sie zu vergessen.

Alle Netzwerkpunkt-Werkzeuge sind zweisprachig. Nachrüsten ist teuer, also
hält dieser Test fest, dass kein sichtbarer Text an der Übersetzung vorbei
ins Template rutscht.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from threaddesk.core import i18n

TEMPLATES = Path(__file__).resolve().parents[1] / "src" / "threaddesk" / "ui" / "templates"
TEMPLATE_FILES = sorted(TEMPLATES.rglob("*.html"))

# Eigennamen, Fachbegriffe und Zeichen, die in beiden Sprachen gleich stehen.
SAME_IN_BOTH = {
    "threaddesk", "thread", "desk", "netzwerkpunkt", "gnom", "gnom-hub-v1",
    "grok", "codex", "notion", "github", "mcp", "json", "csv", "svg", "pdf",
    "snapshot", "snapshots", "handoff", "id", "td", "esc", "enter", "shift",
    "tab", "ok", "api", "ui", "cli", "url", "http", "https",
    "gate", "frozen", "cooldown", "prompt", "label", "optional", "status",
    "generic", "detailed", "short", "steps", "agent", "paket", "packet",
    "threads", "revision", "details", "s", "n", "m", "j", "k",
}
# Satzzeichen und Symbole tragen keine Sprache.
SYMBOLS = re.compile(
    r"^[\s·—–\-−→←↗↑↓+×÷/|,.:;!?()\[\]{}<>#*&%@0-9…\"'`~^=°©§]*$")
# Tastenkuerzel und Beispielpfade tragen keine Sprache.
KBD = re.compile(r"<kbd[^>]*>.*?</kbd>", re.S)
PATHLIKE = re.compile(r"^[\w./~-]+\.[a-z]{1,4}$|^[\w./~-]+/[\w./~-]*$")

JINJA = re.compile(r"\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\}", re.S)
TEXT_NODE = re.compile(r">([^<>]+)<")
# Attribute, die der Nutzer zu sehen bekommt.
VISIBLE_ATTRS = re.compile(
    r"\b(?:aria-label|placeholder|title|alt|aria-description|hx-confirm)"
    r"\s*=\s*\"([^\"]*)\"")


def _human_text(markup: str) -> list[str]:
    """Sichtbarer Text eines Templates, ohne Jinja-Ausdrücke."""
    found: list[str] = []
    markup = KBD.sub("><", markup)
    for raw in TEXT_NODE.findall(markup):
        stripped = JINJA.sub("", raw).strip()
        if stripped and not SYMBOLS.match(stripped):
            found.append(stripped)
    for raw in VISIBLE_ATTRS.findall(markup):
        stripped = JINJA.sub("", raw).strip()
        if stripped and not SYMBOLS.match(stripped):
            found.append(stripped)
    return found


def _unexpected(texts: list[str]) -> list[str]:
    out = []
    for text in texts:
        if PATHLIKE.match(text):
            continue
        words = [w for w in re.split(r"[\s·—–/|,.:;!?()\[\]]+", text) if w]
        if all(w.lower().strip("-") in SAME_IN_BOTH or SYMBOLS.match(w)
               or PATHLIKE.match(w) for w in words):
            continue
        out.append(text)
    return out


# --------------------------------------------------------------- Katalog

def test_every_key_has_both_languages() -> None:
    incomplete = {
        key: [code for code in i18n.LANGUAGES if not entry.get(code)]
        for key, entry in i18n.CATALOG.items()
        if any(not entry.get(code) for code in i18n.LANGUAGES)
    }
    assert not incomplete, f"unvollständige Einträge: {incomplete}"


def test_languages_differ_where_they_should() -> None:
    """Identische Texte sind erlaubt, aber selten — sie sollen auffallen."""
    identical = [key for key, entry in i18n.CATALOG.items()
                 if entry["de"] == entry["en"]]
    # Nur Eigennamen dürfen gleich bleiben.
    unexpected = [key for key in identical
                  if _unexpected([i18n.CATALOG[key]["de"]])]
    assert not unexpected, (
        f"DE und EN gleich, aber kein Eigenname: {unexpected}")


def test_placeholders_match_across_languages() -> None:
    """{name}-Platzhalter müssen in beiden Sprachen dieselben sein."""
    broken = {}
    for key, entry in i18n.CATALOG.items():
        slots = {code: set(re.findall(r"\{(\w+)\}", entry[code]))
                 for code in i18n.LANGUAGES}
        if len(set(map(frozenset, slots.values()))) > 1:
            broken[key] = slots
    assert not broken, f"Platzhalter weichen ab: {broken}"


# --------------------------------------------------------------- Templates

@pytest.mark.parametrize("template", TEMPLATE_FILES,
                         ids=lambda p: str(p.relative_to(TEMPLATES)))
def test_no_hardcoded_text_in_templates(template: Path) -> None:
    """Sichtbarer Text gehört in den Katalog, nicht ins Template.

    Schlägt dieser Test fehl, wurde ein Text hart verdrahtet. Lege einen
    Schlüssel in threaddesk/core/i18n.py an und rufe ihn mit t(...) auf.
    """
    leftovers = _unexpected(_human_text(template.read_text(encoding="utf-8")))
    assert not leftovers, (
        f"{template.name} verdrahtet sichtbaren Text: {leftovers}")


@pytest.mark.parametrize("template", TEMPLATE_FILES,
                         ids=lambda p: str(p.relative_to(TEMPLATES)))
def test_template_keys_exist(template: Path) -> None:
    """Jeder t(...)-Aufruf muss einen Katalogeintrag treffen."""
    used = re.findall(r"""t\(\s*['"]([\w.]+)['"]""",
                      template.read_text(encoding="utf-8"))
    unknown = sorted({key for key in used if key not in i18n.CATALOG})
    assert not unknown, f"{template.name} nutzt unbekannte Schlüssel: {unknown}"


# --------------------------------------------------------------- Auflösung

@pytest.mark.parametrize("given,expected", [
    (None, "de"), ("", "de"), ("de", "de"), ("en", "en"), ("EN", "en"),
    ("de-DE", "de"), ("en_US", "en"), ("fr", "de"), ("klingon", "de"),
])
def test_language_normalisation(given, expected) -> None:
    assert i18n.normalise(given) == expected


@pytest.mark.parametrize("header,expected", [
    (None, "de"),
    ("en-GB,en;q=0.9", "en"),
    ("fr-FR,fr;q=0.9,en;q=0.8", "en"),
    ("de-DE,de;q=0.9", "de"),
    ("fr-FR", "de"),
])
def test_accept_language(header, expected) -> None:
    assert i18n.from_accept_header(header) == expected


def test_unknown_key_returns_key() -> None:
    """Die Oberfläche zerbricht nicht an einem Tippfehler — der Test schon."""
    assert i18n.translate("gibt.es.nicht", "en") == "gibt.es.nicht"


# --------------------------------------------------------------- Durchstich

@pytest.fixture()
def client(tmp_path, monkeypatch):
    fastapi_testclient = pytest.importorskip("fastapi.testclient")
    monkeypatch.setenv("THREADDESK_HOME", str(tmp_path))
    from threaddesk.ui.server import create_app

    return fastapi_testclient.TestClient(create_app())


def test_german_is_the_default(client) -> None:
    page = client.get("/map")
    assert 'lang="de"' in page.text
    assert i18n.translate("map.title", "de") in page.text


def test_query_parameter_switches_language(client) -> None:
    page = client.get("/map?lang=en")
    assert 'lang="en"' in page.text
    assert i18n.translate("map.title", "en") in page.text
    assert i18n.translate("map.title", "de") not in page.text


def test_browser_language_is_honoured(client) -> None:
    page = client.get("/map", headers={"Accept-Language": "en-GB,en;q=0.9"})
    assert 'lang="en"' in page.text
    assert i18n.translate("nav.knowledge", "en") in page.text


def test_switch_route_remembers_the_choice(client) -> None:
    """Der Umschalter setzt ein Cookie und kehrt zurueck."""
    response = client.get("/lang/en", headers={"referer": "/knowledge"},
                          follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/knowledge"
    assert "threaddesk_lang=en" in response.headers["set-cookie"]
    # Danach bleibt Englisch, ohne Parameter.
    assert 'lang="en"' in client.get("/map").text


def test_unknown_language_falls_back_to_german(client) -> None:
    assert 'lang="de"' in client.get("/map?lang=klingon").text


@pytest.mark.parametrize("path", ["/", "/knowledge", "/map"])
def test_every_page_renders_in_both_languages(client, path) -> None:
    """Keine Seite darf in einer Sprache zerbrechen."""
    for code in i18n.LANGUAGES:
        page = client.get(f"{path}?lang={code}")
        assert page.status_code == 200, f"{path} ({code}) antwortet {page.status_code}"
        assert f'lang="{code}"' in page.text


def test_map_hands_its_strings_to_the_browser(client) -> None:
    """Die Kartenlogik bekommt den Katalog, statt Text zu verdrahten."""
    page = client.get("/map?lang=en")
    assert "data-strings=" in page.text
    assert i18n.translate("map.no_details", "en") in page.text
