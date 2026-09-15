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
    "threads", "revision", "details", "import", "s", "n", "m", "j", "k", "person",
    # Zustandswerte und Ausgabemarken, die ThreadDesk unuebersetzt fuehrt.
    "snap", "block", "html", "idea", "active", "paused", "done",
}
# Satzzeichen und Symbole tragen keine Sprache.
SYMBOLS = re.compile(
    r"^[\s·—–\-−→←↗↑↓+×÷/|,.:;!?()\[\]{}<>#*&%@0-9…\"'`~^=°©§]*$")
# Tastenkuerzel und Beispielpfade tragen keine Sprache.
KBD = re.compile(r"<kbd[^>]*>.*?</kbd>", re.S)
PATHLIKE = re.compile(r"^[\w./~-]+\.[a-z]{1,4}$|^[\w./~-]+/[\w./~-]*$")
# {name} wird zur Laufzeit ersetzt und ist in beiden Sprachen derselbe Name.
PLACEHOLDER = re.compile(r"\{[^{}]*\}")

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
        bare = PLACEHOLDER.sub(" ", text)
        words = [w for w in re.split(r"[\s·—–/|,.:;!?()\[\]]+", bare) if w]
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


# Werte, die aus Python kommen, werden ueber einen zusammengesetzten Schluessel
# uebersetzt: t("kind." ~ kind). Statisch ist davon nur das Praefix sichtbar.
# test_every_dropdown_value_has_a_label prueft dafuer jeden moeglichen Wert.
DYNAMIC_PREFIXES = {"kind.", "status.", "relation.", "prompt.target.",
                    "prompt.variant.", "register."}


@pytest.mark.parametrize("template", TEMPLATE_FILES,
                         ids=lambda p: str(p.relative_to(TEMPLATES)))
def test_template_keys_exist(template: Path) -> None:
    """Jeder t(...)-Aufruf muss einen Katalogeintrag treffen."""
    used = re.findall(r"""t\(\s*['"]([\w.]+)['"]""",
                      template.read_text(encoding="utf-8"))
    unknown = sorted({key for key in used
                      if key not in i18n.CATALOG and key not in DYNAMIC_PREFIXES})
    assert not unknown, f"{template.name} nutzt unbekannte Schlüssel: {unknown}"


def test_every_dropdown_value_has_a_label() -> None:
    """Kein Auswahlmenü darf einen rohen Python-Wert zeigen.

    Genau das war der Fehler: die Menüs zeigten `decision`, `in_progress`,
    `depends_on` — unübersetzt, weil die Werte direkt aus dem Modell kamen
    und der Wächter Jinja-Ausdrücke wegschneidet.
    """
    from threaddesk.core import models

    groups = {
        "kind": models.NODE_KINDS,
        "status": models.NODE_STATUSES,
        "relation": models.RELATION_KINDS,
        "prompt.target": ("gnom", "grok", "generic"),
        "prompt.variant": ("detailed", "short", "steps", "agent"),
    }
    missing = [f"{prefix}.{value}"
               for prefix, values in groups.items()
               for value in values
               if f"{prefix}.{value}" not in i18n.CATALOG]
    assert not missing, f"Auswahlwerte ohne Beschriftung: {missing}"


@pytest.mark.parametrize("language", i18n.LANGUAGES)
def test_dropdowns_show_labels_not_raw_values(client, language) -> None:
    """Die gerenderte Seite darf den rohen Wert nicht als Beschriftung tragen."""
    page = client.get(f"/knowledge?lang={language}").text
    offenders = []
    for raw in ("decision", "in_progress", "depends_on", "superseded"):
        if f">{raw}</option>" in page:
            offenders.append(raw)
    assert not offenders, f"roher Wert im Menü ({language}): {offenders}"


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


@pytest.mark.parametrize("language", i18n.LANGUAGES)
def test_post_routes_return_localised_success_and_error(client, language) -> None:
    created = client.post(
        f"/threads?lang={language}",
        data={"title": "Sprachtest", "description": ""},
    )
    assert i18n.translate("ui.created", language, title="Sprachtest") in created.text

    failed = client.post(
        f"/threads?lang={language}", data={"title": " ", "description": ""}
    )
    assert failed.status_code == 400
    assert i18n.translate("ui.error", language) in failed.text


def test_browser_strings_are_injected_for_every_page(client) -> None:
    for path in ("/", "/knowledge", "/map"):
        page = client.get(f"{path}?lang=en")
        assert "data-ui-strings=" in page.text
        assert "Copied" in page.text


def test_no_hardcoded_visible_server_messages() -> None:
    import ast

    source = TEMPLATES.parent / "server.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))
    offenders = [
        f"{node.lineno}: {node.value!r}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
        and WORD.search(node.value)
        and (" " in node.value.strip() or UMLAUT.search(node.value))
    ]
    assert not offenders, "sichtbare Servertexte ohne Katalog:\n" + "\n".join(offenders)


def test_no_hardcoded_visible_javascript_messages() -> None:
    sources = sorted((TEMPLATES.parent / "static").glob("*.js"))
    patterns = (
        r"\.err\s*=\s*[\"'][^\"']*[A-Za-zÄÖÜäöüß]{3,}[^\"']*[\"']",
        r"\.textContent\s*=\s*[\"'][^\"']*[A-Za-zÄÖÜäöüß]{3,}[^\"']*[\"']",
        r"console\.warn\(\s*[\"'][^\"']*[A-Za-zÄÖÜäöüß]{3,}",
    )
    offenders = [
        f"{source.name}: {pattern}"
        for source in sources
        for pattern in patterns
        if re.search(pattern, source.read_text(encoding="utf-8"))
    ]
    assert not offenders, f"sichtbare JavaScript-Texte ohne Katalog: {offenders}"


def test_browser_keys_exist_and_are_used() -> None:
    source = TEMPLATES.parent / "static" / "app.js"
    used = set(re.findall(r'uiText\(["\']([\w.]+)["\']', source.read_text(encoding="utf-8")))
    declared = {key for key in i18n.CATALOG if key.startswith("browser.")}
    assert used == declared


# ----------------------------------------------------------- Kommandozeile

CLI_SOURCE = Path(__file__).resolve().parents[1] / "src" / "threaddesk" / "ui" / "cli.py"

# Ein Literal gilt als Fliesstext, wenn es ein Wort aus drei Buchstaben
# enthaelt UND entweder ein Leerzeichen oder einen Umlaut hat. Damit bleiben
# Bezeichner ("snap="), Schalter ("--max-execute-day") und Formatstuecke
# ("  [") aussen vor, Saetze wie "keine dateien" aber nicht.
WORD = re.compile(r"[A-Za-zÄÖÜäöüß]{3,}")
UMLAUT = re.compile(r"[ÄÖÜäöüß]")
# Argparse erzeugt "usage:", "options:" und "show this help message and exit"
# selbst und nur auf Englisch. Das liegt ausserhalb des Katalogs.
CLI_ALLOWED = {
    "idea | active | paused | done",
}


def _cli_string_literals() -> list[tuple[int, str]]:
    """Alle Zeichenketten aus cli.py ohne Docstrings."""
    import ast

    tree = ast.parse(CLI_SOURCE.read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in docstrings:
                found.append((node.lineno, node.value))
    return found


def test_no_hardcoded_text_in_cli() -> None:
    """Kein sichtbarer Satz darf am Katalog vorbei in die CLI."""
    offenders = [
        f"{CLI_SOURCE.name}:{line}: {text!r}"
        for line, text in _cli_string_literals()
        if text not in CLI_ALLOWED
        and WORD.search(text)
        and (" " in text.strip() or UMLAUT.search(text))
    ]
    assert not offenders, "Text ohne Übersetzung in der CLI:\n" + "\n".join(offenders)


def test_cli_keys_exist() -> None:
    """Jeder Schlüssel, den die CLI nachschlägt, steht im Katalog."""
    used = {text for _, text in _cli_string_literals() if text.startswith("cli.")}
    assert used, "keine cli.-Schlüssel gefunden — der Test greift ins Leere"
    missing = sorted(key for key in used if key not in i18n.CATALOG)
    assert not missing, f"fehlende Schlüssel: {missing}"


def test_every_cli_key_is_used() -> None:
    """Kein toter Schlüssel — sonst wächst der Katalog ins Nichts."""
    used = {text for _, text in _cli_string_literals() if text.startswith("cli.")}
    # Eine Fachfassung wird über ihren Grundschlüssel erreicht, nie direkt.
    # Sie steht deshalb in keinem Aufruf und ist trotzdem nicht tot.
    declared = {key for key in i18n.CATALOG
                if key.startswith("cli.") and not key.endswith(i18n.EXPERT_SUFFIX)}
    assert not (declared - used), f"unbenutzte Schlüssel: {sorted(declared - used)}"


@pytest.mark.parametrize(
    "env,expected",
    [
        ({}, "de"),
        ({"LANG": "C"}, "de"),
        ({"LANG": "POSIX"}, "de"),
        ({"LANG": "en_US.UTF-8"}, "en"),
        ({"LANG": "de_DE.UTF-8"}, "de"),
        ({"LANG": "fr_FR.UTF-8"}, "de"),
        ({"LC_ALL": "en_GB", "LANG": "de_DE"}, "en"),
        ({"LC_ALL": "C", "LANG": "en_GB"}, "en"),
        ({"THREADDESK_LANG": "en", "LANG": "de_DE"}, "en"),
        ({"THREADDESK_LANG": "de", "LC_ALL": "en_US"}, "de"),
    ],
)
def test_language_from_environment(env, expected) -> None:
    assert i18n.from_environment(env) == expected


@pytest.fixture()
def clean_locale(monkeypatch):
    """Keine Locale von aussen — sonst haengt der Test am Laufer."""
    for name in i18n.ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch

@pytest.mark.parametrize(
    "argv,expected",
    [
        (["list"], "de"),
        (["--lang", "en", "list"], "en"),
        (["--lang=en", "list"], "en"),
        (["--lang", "de", "list"], "de"),
        (["--lang", "klingon", "list"], "de"),
    ],
)
def test_cli_flag_beats_environment(clean_locale, argv, expected) -> None:
    from threaddesk.ui import cli

    assert cli.resolve_language(argv) == expected


@pytest.mark.parametrize("language", i18n.LANGUAGES)
def test_cli_help_is_translated(language) -> None:
    """Die Hilfe steht schon beim Bau des Parsers fest — auch die zählt."""
    from threaddesk.ui import cli

    text = cli.build_parser(language).format_help()
    assert i18n.translate("cli.description", language) in text
    assert i18n.translate("cli.help.new", language) in text
    assert i18n.translate("cli.help.serve", language) in text


def test_cli_speaks_both_languages(tmp_path, clean_locale, capsys) -> None:
    """Derselbe Befehl, zwei Sprachen, wirklich unterschiedliche Ausgabe."""
    from threaddesk.storage import json_store
    from threaddesk.ui import cli

    clean_locale.setattr(json_store, "DEFAULT_ROOT", tmp_path / "home")

    assert cli.main(["list"]) == 0
    german = capsys.readouterr().out.strip()
    assert cli.main(["--lang", "en", "list"]) == 0
    english = capsys.readouterr().out.strip()

    assert german == i18n.translate("cli.thread.none", "de")
    assert english == i18n.translate("cli.thread.none", "en")
    assert german != english


def test_cli_output_follows_the_locale(tmp_path, clean_locale, capsys) -> None:
    from threaddesk.storage import json_store
    from threaddesk.ui import cli

    clean_locale.setattr(json_store, "DEFAULT_ROOT", tmp_path / "home")
    clean_locale.setenv("LANG", "en_US.UTF-8")

    assert cli.main(["new", "Karte"]) == 0
    out = capsys.readouterr().out
    assert "created and active" in out
