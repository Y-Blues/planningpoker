"""The Jira import's how-to, drawn into a Drawer's body with ui_web's StepList: five steps, one action each, each with a
small figure (DOM shapes styled by poker.css: a browser and its bookmarks bar, Jira, the room's tree), the bookmark to
drag in step 2, then the read-only note and what to do when it does not work. Every text is a key (strings.py)."""

from typing import Any, Awaitable, Callable

from ycappuccino.ui_web.builder import Builder
from ycappuccino.ui_web.steps import Step, StepList


def render(b: Builder, body: Any, on_copy: Callable[[], Awaitable[None]]) -> tuple[Any, Any]:
    """the how-to under body; returns (the bookmark's link, whose href the page sets, the "copy the bookmark" button)"""
    found: dict = {}

    def drag(parent: Any) -> None:
        found["link"] = b.element(parent, "a", "pp-bookmarklet", "poker.import.bookmarklet", href="#", draggable="true")
        b.text(found["link"], "poker.import.drag_me", "title")

    b.element(body, "p", "pp-tutorial-intro", "poker.tutorial.intro")
    StepList(b).render(body, [
        Step("poker.tutorial.s1", "poker.tutorial.s1.text", illustrate=lambda f: _browser(b, f, keys=True)),
        Step("poker.tutorial.s2", "poker.tutorial.s2.text", illustrate=lambda f: _browser(b, f, dragging=True), extra=drag),
        Step("poker.tutorial.s3", "poker.tutorial.s3.text", illustrate=lambda f: _browser(b, f, jira=True)),
        Step("poker.tutorial.s4", "poker.tutorial.s4.text", illustrate=lambda f: _browser(b, f, clicking=True)),
        Step("poker.tutorial.s5", "poker.tutorial.s5.text", illustrate=lambda f: _tree(b, f)),
    ], label="poker.tutorial.steps")
    b.element(body, "p", "pp-tutorial-readonly", "poker.tutorial.readonly")
    b.element(body, "h3", "pp-tutorial-tips", "poker.tutorial.tips")

    def copy(parent: Any) -> None:
        found["copy"] = b.button(parent, "poker.tutorial.copy", "pp-button pp-ghost pp-tutorial-copy")
        b.dom.on_click(found["copy"], on_copy)

    StepList(b).render(body, [
        Step("poker.tutorial.tip_drag", "poker.tutorial.tip_drag.text", extra=copy),
        Step("poker.tutorial.tip_popup", "poker.tutorial.tip_popup.text"),
        Step("poker.tutorial.tip_login", "poker.tutorial.tip_login.text"),
        Step("poker.tutorial.tip_none", "poker.tutorial.tip_none.text"),
        Step("poker.tutorial.tip_nothing", "poker.tutorial.tip_nothing.text"),
    ], numbered=False, label="poker.tutorial.tips")
    return found["link"], found["copy"]


def _browser(b: Builder, figure: Any, keys: bool = False, dragging: bool = False, jira: bool = False,
             clicking: bool = False) -> None:
    """a small browser window: its address, its bookmarks bar (highlighted where the step acts)"""
    window = b.element(figure, "div", "pp-ill-window")
    top = b.element(window, "div", "pp-ill-top")
    for _ in range(3):
        b.element(top, "i", "pp-ill-dot")
    b.dom.set_text(b.element(top, "span", "pp-ill-address"), "acme.atlassian.net/browse/KP-1" if jira or clicking else "…")
    bar = b.element(window, "div", "pp-ill-bar" + ("" if jira else " is-target"))
    if dragging or jira or clicking:
        b.element(bar, "span", "pp-ill-bookmark" + (" is-dropped" if dragging else "") + (" is-clicked" if clicking else ""),
                  "poker.import.bookmarklet")
    if clicking:
        b.dom.set_text(b.element(bar, "span", "pp-ill-pointer"), "👆")
    page = b.element(window, "div", "pp-ill-page")
    if keys:
        for index, key in enumerate(("Ctrl / ⌘", "Shift", "B")):
            if index:
                b.dom.set_text(b.element(page, "span", "pp-ill-plus"), "+")
            b.dom.set_text(b.element(page, "kbd", "pp-ill-key"), key)
    elif dragging:
        b.dom.set_text(b.element(page, "span", "pp-ill-arrow"), "↑")
    else:
        for kind, number in (("epic", "KP-1"), ("story", "KP-2"), ("story", "KP-4")):
            row = b.element(page, "div", "pp-ill-row")
            b.element(row, "span", "pp-kind is-" + kind, "poker.kind." + kind)
            b.dom.set_text(b.element(row, "span", "pp-ill-key-text"), number)


def _tree(b: Builder, figure: Any) -> None:
    """the room's tree once imported: Epic › Story › Sub-task"""
    tree = b.element(figure, "div", "pp-ill-tree")
    for depth, (kind, number) in enumerate((("epic", "KP-1"), ("story", "KP-2"), ("subtask", "KP-3"))):
        row = b.element(tree, "div", f"pp-ill-row pp-depth-{depth}")
        b.element(row, "span", "pp-kind is-" + kind, "poker.kind." + kind)
        b.dom.set_text(b.element(row, "span", "pp-ill-key-text"), number)
