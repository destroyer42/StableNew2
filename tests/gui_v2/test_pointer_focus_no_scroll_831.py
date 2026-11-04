"""PR-GUI-RELIABILITY-831 (finding F2): focus gained by a mouse press must not scroll the page under the pointer.

The page-wide ``<FocusIn>`` reveal (PR-GUI-400) scrolled a partly clipped control into view while the mouse button
was still down, so the release landed on whatever had scrolled under the pointer.  A control the pointer is already
on is visible; only focus that arrives elsewhere (Tab, programmatic) reveals.
"""

from __future__ import annotations

import tkinter as tk

import pytest

from src.gui.widgets.scrollable_frame_v2 import _WheelRouter
from tests.gui_v2.test_scrollable_focus_reveal_400 import (
    _focus,
    _frame_with_buttons,
    _is_visible,
)


def _pointer_on(monkeypatch: pytest.MonkeyPatch, widget: tk.Misc | None) -> None:
    """Pin both pointer lookups: ``winfo_containing`` is real OS hit-testing on Windows, so another window changes it."""

    monkeypatch.setattr(tk.Misc, "winfo_pointerxy", lambda self: (1, 1))
    monkeypatch.setattr(tk.Misc, "winfo_containing", lambda self, x, y, displayof=False: widget)


def _clipped_button(frame, buttons):
    """A button whose top is inside the viewport and whose bottom edge is cut off by it."""
    viewport_bottom = frame._canvas.winfo_rooty() + frame._canvas.winfo_height()  # noqa: SLF001
    for button in buttons:
        top = button.winfo_rooty()
        if top < viewport_bottom < top + button.winfo_height():
            return button
    pytest.skip("no partly clipped button at this font size")


def test_focus_on_the_control_under_the_pointer_does_not_scroll(
    tk_root: tk.Tk, monkeypatch: pytest.MonkeyPatch
) -> None:
    frame, buttons = _frame_with_buttons(tk_root)
    try:
        # scroll so one button straddles the bottom edge, like the Add to Job / Steps controls in the journeys
        frame._canvas.yview_scroll(1, "units")  # noqa: SLF001
        tk_root.update()
        target = _clipped_button(frame, buttons)
        before = frame._canvas.yview()  # noqa: SLF001
        _pointer_on(monkeypatch, target)

        _focus(tk_root, target)

        assert frame._canvas.yview() == before  # noqa: SLF001
    finally:
        frame.destroy()


def test_focus_elsewhere_still_reveals_the_clipped_control(
    tk_root: tk.Tk, monkeypatch: pytest.MonkeyPatch
) -> None:
    frame, buttons = _frame_with_buttons(tk_root)
    try:
        frame._canvas.yview_scroll(1, "units")  # noqa: SLF001
        tk_root.update()
        target = _clipped_button(frame, buttons)
        _pointer_on(monkeypatch, None)

        _focus(tk_root, target)

        assert _is_visible(frame, target)
    finally:
        frame.destroy()


def test_pointer_over_is_true_for_a_descendant_of_the_focused_widget_only(
    tk_root: tk.Tk, monkeypatch: pytest.MonkeyPatch
) -> None:
    frame, buttons = _frame_with_buttons(tk_root)
    try:
        first, second = buttons[0], buttons[1]
        _pointer_on(monkeypatch, first)
        assert _WheelRouter._pointer_over(first)  # noqa: SLF001
        assert _WheelRouter._pointer_over(frame.inner)  # noqa: SLF001 - an ancestor contains the pointer too
        assert not _WheelRouter._pointer_over(second)  # noqa: SLF001
        _pointer_on(monkeypatch, None)
        assert not _WheelRouter._pointer_over(first)  # noqa: SLF001
    finally:
        frame.destroy()


def test_a_nested_scroll_box_at_its_limit_hands_the_wheel_to_the_page(
    tk_root: tk.Tk, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A nested box at its end must not trap the wheel: the page behind it scrolls (finding F1/F7 follow-up)."""

    from tkinter import ttk
    from types import SimpleNamespace

    from src.gui.widgets.scrollable_frame_v2 import ScrollableFrame

    tk_root.geometry("360x300+50+50")
    tk_root.deiconify()
    outer = ScrollableFrame(tk_root)
    outer.place(relx=0, rely=0, relwidth=1, relheight=1)
    for row in range(30):
        ttk.Label(outer.inner, text=f"page row {row}").pack()
    inner = ScrollableFrame(outer.inner)
    inner.pack(fill="x")
    for row in range(30):
        ttk.Label(inner.inner, text=f"box row {row}").pack()
    tk_root.update()
    try:
        router = _WheelRouter.for_widget(tk_root)
        monkeypatch.setattr(router, "_frames_under_pointer", lambda x, y: [inner, outer])
        event = SimpleNamespace(x_root=5, y_root=5)

        assert router._dispatch(event, 1) == "break"  # noqa: SLF001
        assert inner._canvas.yview()[0] > 0.0 and outer._canvas.yview()[0] == 0.0  # noqa: SLF001

        inner._canvas.yview_moveto(1.0)  # noqa: SLF001 - the box is now at its end
        tk_root.update()
        assert router._dispatch(event, 1) == "break"  # noqa: SLF001
        assert outer._canvas.yview()[0] > 0.0  # noqa: SLF001 - the page took the wheel

        inner._canvas.yview_moveto(0.0)  # noqa: SLF001 - and at the box's top, scrolling up goes to the page
        outer._canvas.yview_moveto(0.5)  # noqa: SLF001
        tk_root.update()
        before = outer._canvas.yview()[0]  # noqa: SLF001
        assert router._dispatch(event, -1) == "break"  # noqa: SLF001
        assert outer._canvas.yview()[0] < before  # noqa: SLF001
    finally:
        outer.destroy()


def test_a_wheel_notch_moves_at_least_a_readable_step_even_in_a_short_pane(tk_root: tk.Tk) -> None:
    """Tk's own unit is a tenth of the window: in an 88 px pane that is under 10 px per notch."""

    from tkinter import ttk

    from src.gui.widgets.scrollable_frame_v2 import ScrollableFrame

    tk_root.geometry("360x300+50+50")
    tk_root.deiconify()
    frame = ScrollableFrame(tk_root)
    frame.place(x=0, y=0, width=360, height=90)
    for row in range(60):
        ttk.Label(frame.inner, text=f"row {row}").pack()
    tk_root.update()
    try:
        span = frame._canvas.bbox("all")[3]  # noqa: SLF001
        frame.scroll_units(1)
        moved = frame._canvas.yview()[0] * span  # noqa: SLF001
        assert moved >= 39.0
        frame.scroll_units(-1)
        assert frame._canvas.yview()[0] == pytest.approx(0.0, abs=1e-6)  # noqa: SLF001
        frame.scroll_units(10_000)
        assert frame._canvas.yview()[1] == pytest.approx(1.0)  # noqa: SLF001
    finally:
        frame.destroy()
