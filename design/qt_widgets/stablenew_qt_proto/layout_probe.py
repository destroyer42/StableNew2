"""Deterministic layout measurements for the Create workflow (reachability, scrolling, clipping, focus).

Used by ``tools/layout_audit.py`` (evidence) and the Qt tests. It only inspects widget geometry and
moves focus/scroll position inside the prototype window; it submits nothing and writes nothing.
"""

from __future__ import annotations

import math
from typing import Any

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QScrollArea, QWidget

from .components import reveal
from .create_view import CreateView
from .edit_domain import CREATE_SOURCE, Mode

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
    for scroll in view.scroll_areas:
        body = scroll.widget()
        if body is not None and scroll.isVisible() and body.isAncestorOf(widget):
            return scroll
    return None


def _area_name(view: CreateView, scroll: QScrollArea | None) -> str:
    return {
        view.form_scroll: "form",
        view.settings_scroll: "settings",
        view.review_scroll: "review",
    }.get(scroll, "fixed")


def control_report(view: CreateView, name: str) -> dict[str, Any]:
    widget = _control(view, name)
    scroll = _scroll_of(view, widget)
    window = view.window()
    report: dict[str, Any] = {
        "control": name,
        "area": _area_name(view, scroll),
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
            tl.x() < 0 or br.x() >= viewport.width() or tl.y() < 0 or br.y() > viewport.height()
        )
        report["reachable"] = not report["clipped"]
    else:
        tl, br = (
            widget.mapTo(window, widget.rect().topLeft()),
            widget.mapTo(window, widget.rect().bottomRight()),
        )
        report["screens_from_top"] = 1
        report["clipped"] = bool(
            tl.x() < 0 or tl.y() < 0 or br.x() >= window.width() or br.y() > window.height()
        )
        report["reachable"] = not report["clipped"]
    return report


def task_path_report(view: CreateView) -> dict[str, Any]:
    """Scroll distance and actions needed to touch each task control in order, starting from the top."""
    for scroll in view.scroll_areas:
        scroll.verticalScrollBar().setValue(0)
    QApplication.processEvents()
    distance = {"form": 0, "settings": 0, "review": 0}
    actions = 0
    for name in TASK_PATH:
        widget = _control(view, name)
        scroll = _scroll_of(view, widget)
        if scroll is None:
            continue
        bar = scroll.verticalScrollBar()
        before = bar.value()
        reveal(scroll, widget, margin=0)
        QApplication.processEvents()
        if bar.value() != before:
            actions += 1
            distance[_area_name(view, scroll)] += abs(bar.value() - before)
    viewport = max(1, view.form_scroll.viewport().height())
    for scroll in view.scroll_areas:
        scroll.verticalScrollBar().setValue(0)
    return {
        "steps": len(TASK_PATH),
        "scroll_actions": actions,
        "interactions": len(TASK_PATH) + actions,
        "form_scroll_px": distance["form"],
        "settings_scroll_px": distance["settings"],
        "review_scroll_px": distance["review"],
        "form_scroll_viewports": round(distance["form"] / viewport, 2),
    }


def keyboard_report(window: QWidget, view: CreateView, limit: int = 260) -> dict[str, Any]:
    """Walk the Tab chain from the first control; record coverage and any focus that lands out of view."""
    app = QApplication.instance()
    for scroll in view.scroll_areas:
        scroll.verticalScrollBar().setValue(0)
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


def text_clipping(view: CreateView) -> list[str]:
    """Check visible text using the active font and Qt's styled content rectangles."""
    from PySide6.QtCore import QRect, Qt
    from PySide6.QtWidgets import (
        QCheckBox,
        QComboBox,
        QLabel,
        QPushButton,
        QStyle,
        QStyleOptionButton,
        QStyleOptionComboBox,
    )

    clipped = []
    for widget in view.findChildren(QWidget):
        if not widget.isVisibleTo(view):
            continue
        flags = Qt.TextFlag.TextShowMnemonic
        if isinstance(widget, QComboBox):
            option = QStyleOptionComboBox()
            widget.initStyleOption(option)
            rect = widget.style().subControlRect(
                QStyle.ComplexControl.CC_ComboBox,
                option,
                QStyle.SubControl.SC_ComboBoxEditField,
                widget,
            )
            text = widget.currentText()
        elif isinstance(widget, (QCheckBox, QPushButton)):
            option = QStyleOptionButton()
            widget.initStyleOption(option)
            element = (
                QStyle.SubElement.SE_CheckBoxContents
                if isinstance(widget, QCheckBox)
                else QStyle.SubElement.SE_PushButtonContents
            )
            rect = widget.style().subElementRect(element, option, widget)
            text = widget.text()
        elif isinstance(widget, QLabel):
            rect = widget.contentsRect()
            text = widget.text()
            flags = Qt.TextFlag.TextWordWrap if widget.wordWrap() else Qt.TextFlag(0)
        else:
            continue
        metrics = widget.fontMetrics()
        bounds = metrics.boundingRect(QRect(0, 0, rect.width(), 4096), flags, text)
        if text and (bounds.width() > rect.width() + 1 or bounds.height() > rect.height() + 2):
            clipped.append(text)
    return clipped


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
            _area_name(view, scroll)
            for scroll in view.scroll_areas
            if scroll.isVisible() and scroll.widget().width() > scroll.viewport().width()
        ],
    }
    # What is visible without any scrolling (persistent information).
    for scroll in view.scroll_areas:
        scroll.verticalScrollBar().setValue(0)
    pump(QApplication.instance(), 2)
    report["pane_geometry"] = {
        _area_name(view, scroll): {
            "viewport": [scroll.viewport().width(), scroll.viewport().height()],
            "content_height": scroll.widget().height(),
            "vertical_range": scroll.verticalScrollBar().maximum(),
        }
        for scroll in view.scroll_areas
        if scroll.isVisible()
    }
    report["clipped_text"] = text_clipping(view)
    report["visible_required_controls"] = [
        name for name in names if _in_view_unscrolled(view, _control(view, name))
    ]
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
    return _contained(widget, area)


def _contained(widget: QWidget, area: QWidget) -> bool:
    if not widget.isVisibleTo(area):
        return False
    tl, br = (
        widget.mapTo(area, widget.rect().topLeft()),
        widget.mapTo(area, widget.rect().bottomRight()),
    )
    return tl.x() >= 0 and tl.y() >= 0 and br.x() <= area.width() and br.y() <= area.height()


def prime_edit(window, size: tuple[int, int], state: str = "masked") -> None:
    """Prepare an Edit evidence case, including a native pointer stroke in Masked Edit."""
    app = QApplication.instance()
    view = window.edit_view
    window.nav.setCurrentRow(window.pages.indexOf(view))
    window.show()
    pump(app)
    window.resize(*size)
    window.activateWindow()
    pump(app)
    view.select_source(CREATE_SOURCE)
    view.mode.setCurrentText(Mode.EXTEND if state in ("extend", "blocked") else Mode.MASKED)
    QTest.keyClicks(view.prompt, "Warm the light on the ridgeline")
    if state in ("extend", "blocked"):
        view.margins["left"].setValue(96 if state == "extend" else 0)
        view.margins["top"].setValue(48 if state == "extend" else 0)
        if state == "blocked":
            view.margins["right"].setValue(0)
    else:
        pump(app)
        canvas = view.canvas
        tx = canvas.transform()
        start = QPoint(round(tx.left + 170 * tx.scale), round(tx.top + 260 * tx.scale))
        end = QPoint(round(tx.left + 410 * tx.scale), round(tx.top + 222 * tx.scale))
        view.brush.setValue(28)
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(canvas, end)
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=end)
    view.preview_button.click()
    if state == "compare":
        view.admit_button.click()
    elif state != "blocked":
        view.inspector.setCurrentWidget(view.settings_scroll)
    pump(app)


def probe_edit(window) -> dict[str, Any]:
    """Measure persistent Edit controls, inspector overflow and the enabled Tab chain."""
    view = window.edit_view
    controls = {
        "source": view.picker,
        "mode": view.mode,
        "inspector": view.inspector_toggle,
        "canvas": view.canvas,
        "fit": view.zoom.buttons["Fit to Window"],
        "actual_size": view.zoom.buttons["100%"],
        "zoom_in": view.zoom.buttons["Zoom in"],
        "zoom_out": view.zoom.buttons["Zoom out"],
        "tool": view.tool,
        "brush": view.brush,
        "undo": view.undo,
        "redo": view.redo,
        "clear_mask": view.clear_mask,
        "build_preview": view.preview_button,
        "simulated_admission": view.admit_button,
        "compare": view.compare_button,
    }

    def visible_through_parents(widget: QWidget) -> bool:
        area = widget.parentWidget()
        while area is not None:
            if not _contained(widget, area):
                return False
            if area is window:
                break
            area = area.parentWidget()
        return True

    clipped = [name for name, widget in controls.items() if not visible_through_parents(widget)]
    app = QApplication.instance()
    scroll = view.settings_scroll
    inspector_controls = {
        "profile": view.profile,
        "region": view.region,
        "prompt": view.prompt,
        "negative": view.negative,
        "advanced": view.advanced.toggle,
    }
    task_scroll = {}
    for name, widget in inspector_controls.items():
        scroll.verticalScrollBar().setValue(0)
        reveal(scroll, widget)
        task_scroll[name] = scroll.verticalScrollBar().value()
    scroll.verticalScrollBar().setValue(0)
    view.picker.setFocus()
    pump(app, 2)
    seen = []
    for _ in range(100):
        focus = app.focusWidget()
        if focus is None or focus in seen:
            break
        seen.append(focus)
        window.focusNextChild()
        pump(app, 1)
    required = {
        name: widget
        for name, widget in (controls | inspector_controls).items()
        if widget.isEnabled() and widget.isVisibleTo(window)
    }
    missing = [
        name
        for name, widget in required.items()
        if not any(w is widget or widget.isAncestorOf(w) for w in seen)
    ]
    return {
        "layout": view.layout_design,
        "window": window.size().toTuple(),
        "canvas": view.canvas.size().toTuple(),
        "inspector_viewport": scroll.viewport().size().toTuple(),
        "settings_scroll_px": task_scroll,
        "horizontal_overflow_px": max(0, scroll.widget().width() - scroll.viewport().width()),
        "clipped": clipped,
        "tab_stops": len(seen),
        "missing_tab_stops": missing,
        "preview": view.session.status,
    }
