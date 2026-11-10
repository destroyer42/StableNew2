"""Deterministic layout measurements for the Create workflow (reachability, scrolling, clipping, focus).

Used by ``tools/layout_audit.py`` (evidence) and the Qt tests. It only inspects widget geometry and
moves focus/scroll position inside the prototype window; it submits nothing and writes nothing.
"""

from __future__ import annotations

import math
from typing import Any

from PySide6.QtWidgets import QApplication, QScrollArea, QWidget

from .components import reveal
from .create_view import CreateView

# Controls an operator must be able to reach to complete the Create task (attribute name on CreateView).
REQUIRED_CONTROLS: tuple[str, ...] = (
    "source_combo",
    "prompt_text",
    "model_combo",
    "profile_combo",
    "size_combo",
    "reset_unlocked_button",
    "preview_button",
    "admit_button",
    "undo_button",
    "redo_button",
    "reset_button",
)
REQUIRED_SETTINGS: tuple[str, ...] = ("steps", "cfg", "seed", "batch")
# The ordered task: pick a source, write a prompt, choose a model, tune steps, preview, admit.
TASK_PATH: tuple[str, ...] = (
    "source_combo",
    "prompt_text",
    "model_combo",
    "setting:steps",
    "preview_button",
    "admit_button",
)


def pump(app: QApplication, rounds: int = 6) -> None:
    for _ in range(rounds):
        app.processEvents()


def _control(view: CreateView, name: str) -> QWidget:
    if name.startswith("setting:"):
        return view.setting_inputs[name.split(":", 1)[1]]
    return getattr(view, name)


def _scroll_of(view: CreateView, widget: QWidget) -> QScrollArea | None:
    for scroll in (view.form_scroll, view.review_scroll):
        body = scroll.widget()
        if body is not None and scroll.isVisible() and body.isAncestorOf(widget):
            return scroll
    return None


def _scroll_state(scroll: QScrollArea | None) -> int:
    return scroll.verticalScrollBar().value() if scroll is not None else 0


def control_report(view: CreateView, name: str) -> dict[str, Any]:
    widget = _control(view, name)
    scroll = _scroll_of(view, widget)
    window = view.window()
    report: dict[str, Any] = {
        "control": name,
        "area": "fixed" if scroll is None else ("form" if scroll is view.form_scroll else "review"),
        "visible_in_tree": widget.isVisibleTo(window),
    }
    if not report["visible_in_tree"]:
        report.update(
            reachable=False,
            reason="hidden (collapsed disclosure or hidden pane)",
            screens_from_top=None,
            clipped=None,
        )
        return report
    if scroll is not None:
        body, viewport = scroll.widget(), scroll.viewport()
        top = widget.mapTo(body, widget.rect().topLeft()).y()
        report["screens_from_top"] = max(
            1, math.ceil((top + widget.height()) / max(1, viewport.height()))
        )
        reveal(scroll, widget)
        QApplication.processEvents()
        rect = widget.rect()
        tl, br = widget.mapTo(viewport, rect.topLeft()), widget.mapTo(viewport, rect.bottomRight())
        report["clipped"] = bool(
            tl.x() < 0 or br.x() > viewport.width() or tl.y() < 0 or br.y() > viewport.height()
        )
        report["reachable"] = not report["clipped"]
    else:
        tl, br = (
            widget.mapTo(window, widget.rect().topLeft()),
            widget.mapTo(window, widget.rect().bottomRight()),
        )
        report["screens_from_top"] = 1
        report["clipped"] = bool(
            tl.x() < 0 or tl.y() < 0 or br.x() > window.width() or br.y() > window.height()
        )
        report["reachable"] = not report["clipped"]
    return report


def task_path_report(view: CreateView) -> dict[str, Any]:
    """Scroll distance and actions needed to touch each task control in order, starting from the top."""
    for scroll in (view.form_scroll, view.review_scroll):
        scroll.verticalScrollBar().setValue(0)
    QApplication.processEvents()
    distance = {"form": 0, "review": 0}
    actions = 0
    last = {"form": 0, "review": 0}
    for name in TASK_PATH:
        widget = _control(view, name)
        scroll = _scroll_of(view, widget)
        if scroll is None:
            continue
        key = "form" if scroll is view.form_scroll else "review"
        reveal(scroll, widget)
        QApplication.processEvents()
        value = _scroll_state(scroll)
        if value != last[key]:
            actions += 1
            distance[key] += abs(value - last[key])
            last[key] = value
    viewport = max(1, view.form_scroll.viewport().height())
    for scroll in (view.form_scroll, view.review_scroll):
        scroll.verticalScrollBar().setValue(0)
    return {
        "steps": len(TASK_PATH),
        "scroll_actions": actions,
        "interactions": len(TASK_PATH) + actions,
        "form_scroll_px": distance["form"],
        "review_scroll_px": distance["review"],
        "form_scroll_viewports": round(distance["form"] / viewport, 2),
    }


def keyboard_report(window: QWidget, view: CreateView, limit: int = 260) -> dict[str, Any]:
    """Walk the Tab chain from the first control; record coverage and any focus that lands out of view."""
    app = QApplication.instance()
    view.form_scroll.verticalScrollBar().setValue(0)
    view.review_scroll.verticalScrollBar().setValue(0)
    pump(app, 2)
    first = view.source_combo
    first.setFocus()
    pump(app, 2)
    seen: list[QWidget] = []
    out_of_view = 0
    for _ in range(limit):
        current = QApplication.focusWidget()
        if current is None or (seen and current is seen[0]):
            break
        seen.append(current)
        scroll = _scroll_of(view, current)
        if scroll is not None:
            viewport = scroll.viewport()
            tl, br = (
                current.mapTo(viewport, current.rect().topLeft()),
                current.mapTo(viewport, current.rect().bottomRight()),
            )
            tall = current.height() > viewport.height()
            if (
                br.y() < 0
                or tl.y() > viewport.height()
                or (not tall and (tl.y() < 0 or br.y() > viewport.height()))
            ):
                out_of_view += 1
        window.focusNextChild()
        pump(app, 1)
    wanted = [*REQUIRED_CONTROLS, *(f"setting:{n}" for n in REQUIRED_SETTINGS)]

    def in_chain(control: QWidget) -> bool:  # spin boxes focus their inner line edit
        return any(w is control or control.isAncestorOf(w) for w in seen)

    def tabbable(control: QWidget) -> bool:
        return control.isVisibleTo(window) and control.isEnabled()

    missing = [n for n in wanted if tabbable(_control(view, n)) and not in_chain(_control(view, n))]
    disabled = [
        n
        for n in wanted
        if _control(view, n).isVisibleTo(window) and not _control(view, n).isEnabled()
    ]
    order = {id(w): i for i, w in enumerate(seen)}
    preview_index = next((order[id(w)] for w in seen if w is view.preview_text), None)
    preview_button_index = next((order[id(w)] for w in seen if w is view.preview_button), None)
    return {
        "tab_stops": len(seen),
        "required_missing_from_chain": missing,
        "required_disabled_in_state": disabled,
        "focus_out_of_view": out_of_view,
        # The preview text must be reached before the actions that build/admit it (visual order).
        "preview_before_actions": preview_index is not None
        and preview_button_index is not None
        and preview_index < preview_button_index,
    }


def prime(window: QWidget) -> None:
    """Put the mock draft in the busiest realistic state: one manual override, a current ready preview.

    Enables Undo, Reset-unlocked and Simulate admission so keyboard and reachability checks cover them.
    Only the in-memory mock session changes.
    """
    view: CreateView = window.create_view  # type: ignore[attr-defined]
    steps = view.setting_inputs["steps"]
    steps.setValue(steps.value() + 7)
    view.preview_button.click()
    pump(QApplication.instance(), 3)


def probe(window: QWidget, *, with_keyboard: bool = True, primed: bool = False) -> dict[str, Any]:
    """Full measurement of the current window state (call after ``show`` and event processing)."""
    if primed:
        prime(window)
    view: CreateView = window.create_view  # type: ignore[attr-defined]
    form_vp = view.form_scroll.viewport()
    names = [*REQUIRED_CONTROLS, *(f"setting:{n}" for n in REQUIRED_SETTINGS)]
    controls = [control_report(view, n) for n in names]
    report: dict[str, Any] = {
        "layout": view.layout_design,
        "state": "primed" if primed else "fresh",
        "window": [window.width(), window.height()],
        "output_display": "collapsed" if window.output_dock.collapsed else "expanded",
        "view": [view.width(), view.height()],
        "form_viewport": [form_vp.width(), form_vp.height()],
        "form_content_height": view.form_scroll.widget().height(),
        "form_screens": round(view.form_scroll.widget().height() / max(1, form_vp.height()), 2),
        "review_viewport": [
            view.review_scroll.viewport().width(),
            view.review_scroll.viewport().height(),
        ]
        if view.review_scroll.isVisible()
        else None,
        "review_screens": round(
            view.review.height() / max(1, view.review_scroll.viewport().height()), 2
        )
        if view.review_scroll.isVisible()
        else None,
        "chrome_px": window.height() - form_vp.height(),
        "controls": controls,
        "unreachable": [c["control"] for c in controls if not c["reachable"]],
        "settings_columns": view.settings_grid.columns,
        "min_size_hint": [window.minimumSizeHint().width(), window.minimumSizeHint().height()],
        "min_hint_fits": window.minimumSizeHint().width() <= window.width()
        and window.minimumSizeHint().height() <= window.height(),
        "horizontal_overflow": [
            scroll_name
            for scroll_name, scroll in (("form", view.form_scroll), ("review", view.review_scroll))
            if scroll.isVisible()
            and scroll.widget().minimumSizeHint().width() > scroll.viewport().width()
        ],
    }
    # What is visible without any scrolling (persistent information).
    for scroll in (view.form_scroll, view.review_scroll):
        scroll.verticalScrollBar().setValue(0)
    pump(QApplication.instance(), 2)
    report["persistent_without_scroll"] = {
        name: _in_view_unscrolled(view, widget)
        for name, widget in (
            ("preview_chip", view.preview_chip),
            ("summary", view.summary_label),
            ("preview_button", view.preview_button),
            ("admit_button", view.admit_button),
        )
    }
    report["task_path"] = task_path_report(view)
    if with_keyboard:
        report["keyboard"] = keyboard_report(window, view)
    return report


def _in_view_unscrolled(view: CreateView, widget: QWidget) -> bool:
    if not widget.isVisibleTo(view.window()):
        return False
    scroll = _scroll_of(view, widget)
    area = scroll.viewport() if scroll is not None else view.window()
    tl, br = (
        widget.mapTo(area, widget.rect().topLeft()),
        widget.mapTo(area, widget.rect().bottomRight()),
    )
    return tl.x() >= 0 and tl.y() >= 0 and br.x() <= area.width() and br.y() <= area.height()
