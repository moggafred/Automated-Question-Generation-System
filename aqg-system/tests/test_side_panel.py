"""Side-panel hide/show affordances.

Every right-hand panel is marked with ``data-rail`` so the shell can hide all of
them from a single top-bar toggle and remember the choice in ``localStorage``.
These are static checks over the shipped markup, because the behaviour itself is
client-side JavaScript.
"""

from pathlib import Path

from fastapi.testclient import TestClient

from main import app

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PAGES = PROJECT_ROOT / "static" / "js" / "pages"

#: Pages that render a right-hand panel the user should be able to hide.
RAIL_PAGES = {"dashboard.js", "generate.js", "study.js", "quiz.js", "help.js", "home.js"}


def test_index_exposes_the_side_panel_toggle():
    html = TestClient(app).get("/").text

    start = html.find('id="rail-toggle"')
    assert start != -1, "top bar must expose the side-panel toggle"

    button = html[max(0, start - 250) : start + 450]
    # Hidden on load, revealed by the router only when a rail is present.
    assert "hidden" in button
    assert 'aria-pressed="true"' in button
    assert "panelRightClose" in button


def test_every_right_hand_panel_is_marked_with_data_rail():
    marked = {
        path.name
        for path in PAGES.glob("*.js")
        if "data-rail" in path.read_text(encoding="utf-8")
    }
    assert RAIL_PAGES <= marked, f"Missing data-rail marker in: {sorted(RAIL_PAGES - marked)}"


def test_shell_hides_marked_rails_and_the_toggle_remembers_the_choice():
    shell = (PROJECT_ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
    store = (PROJECT_ROOT / "static" / "js" / "store.js").read_text(encoding="utf-8")
    css = (PROJECT_ROOT / "static" / "css" / "app.css").read_text(encoding="utf-8")

    # The remembered preference is written to localStorage and applied on boot.
    assert "rail: 'aqg.rail'" in store
    assert "setRailHidden" in store
    assert "dataset.rail = hidden ? 'hidden' : 'shown'" in shell
    assert "querySelector('[data-rail]')" in shell

    # CSS collapses the layout and removes the panel when hidden.
    assert "[data-rail='hidden']" in css
    assert "[data-rail]" in css
