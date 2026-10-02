"""Der Schreibtisch füllt das Fenster. Die Seite scrollt nicht als Ganzes."""

from __future__ import annotations

from pathlib import Path

UI = Path(__file__).resolve().parents[1] / "src" / "threaddesk" / "ui"
STYLE = (UI / "static" / "style.css").read_text(encoding="utf-8")
POLISH = (UI / "static" / "polish.css").read_text(encoding="utf-8")
DETAIL = (UI / "templates" / "partials" / "thread_detail.html").read_text(encoding="utf-8")
NOTES = (UI / "templates" / "partials" / "notes.html").read_text(encoding="utf-8")


def test_desk_uses_named_grid_so_tools_sit_beside_notes() -> None:
    assert 'class="desk-head"' in DETAIL
    assert "desk-notes" in NOTES
    assert 'class="desk-side"' in DETAIL
    assert "grid-template-areas" in STYLE
    assert '"notes' in STYLE or "notes" in STYLE
    assert "desk-side" in STYLE or '"side"' in STYLE


def test_notes_field_does_not_force_a_tall_page() -> None:
    assert 'rows="8"' not in NOTES


def test_window_is_a_fixed_desk_not_a_scrolling_document() -> None:
    assert "100dvh" in STYLE
    assert "overflow: clip" in STYLE
    assert ".main" in STYLE
    main = STYLE[STYLE.index(".main {"):]
    main = main[: main.index("}")]
    assert "overflow: clip" in main or "overflow: hidden" not in main
    assert "overflow: auto" not in main
