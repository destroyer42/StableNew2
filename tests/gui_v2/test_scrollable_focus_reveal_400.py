"""PR-GUI-400: a control that takes keyboard focus is scrolled into view (found by a real-Tab inspection).

Tab used to move focus into controls scrolled out of view (42 of 76 tab stops on the Pipeline tab). The shared
``ScrollableFrame`` router now reveals the focused widget. Focus is simulated with ``<FocusIn>`` so the tests do not
depend on the OS giving the test window the keyboard.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import pytest

from src.gui.widgets.scrollable_frame_v2 import ScrollableFrame, _WheelRouter


def _show(root: tk.Tk) -> None:
    """The shared fixture withdraws the root, and Tk lays a withdrawn window's canvases out at 1 px tall."""

    root.geometry("360x240+50+50")
    root.deiconify()
    root.update()


def _frame_with_buttons(root: tk.Tk, count: int = 30) -> tuple[ScrollableFrame, list[ttk.Button]]:
    _show(root)
    frame = ScrollableFrame(root)
    frame.place(relx=0, rely=0, relwidth=1, relheight=1)
    buttons = []
    for row in range(count):
        button = ttk.Button(frame.inner, text=f"Button {row}")
        button.grid(row=row, column=0, sticky="w", pady=2)
        buttons.append(button)
    root.update_idletasks()
    root.update()
    return frame, buttons


def _is_visible(frame: ScrollableFrame, widget: tk.Misc) -> bool:
    top = 0
    node: tk.Misc | None = widget
    while node is not None and node is not frame.inner:
        top += node.winfo_y()
        node = node.master
    first, _ = frame._canvas.yview()  # noqa: SLF001
    visible_top = first * frame.inner.winfo_height()
    visible_bottom = visible_top + frame._canvas.winfo_height()  # noqa: SLF001
    return top >= visible_top - 1 and top + widget.winfo_height() <= visible_bottom + 1


def _focus(root: tk.Tk, widget: tk.Misc) -> None:
    widget.event_generate("<FocusIn>")
    root.update_idletasks()


def test_focus_below_the_fold_scrolls_down_to_the_control(tk_root: tk.Tk) -> None:
    frame, buttons = _frame_with_buttons(tk_root)
    try:
        assert frame.has_scroll_overflow()
        assert not _is_visible(frame, buttons[-1]), (
            "precondition: the last button starts out of view"
        )
        _focus(tk_root, buttons[-1])
        assert _is_visible(frame, buttons[-1])
        assert frame._canvas.yview()[0] > 0  # noqa: SLF001
    finally:
        frame.destroy()


def test_focus_back_at_the_top_scrolls_up(tk_root: tk.Tk) -> None:
    frame, buttons = _frame_with_buttons(tk_root)
    try:
        _focus(tk_root, buttons[-1])
        assert frame._canvas.yview()[0] > 0  # noqa: SLF001
        _focus(tk_root, buttons[0])
        assert _is_visible(frame, buttons[0])
        assert frame._canvas.yview()[0] == pytest.approx(0.0, abs=0.01)  # noqa: SLF001
    finally:
        frame.destroy()


def test_focus_on_an_already_visible_control_does_not_scroll(tk_root: tk.Tk) -> None:
    frame, buttons = _frame_with_buttons(tk_root)
    try:
        assert _is_visible(frame, buttons[1])
        _focus(tk_root, buttons[1])
        assert frame._canvas.yview()[0] == 0.0  # noqa: SLF001
    finally:
        frame.destroy()


def test_each_tab_stop_in_order_becomes_visible(tk_root: tk.Tk) -> None:
    frame, buttons = _frame_with_buttons(tk_root, count=40)
    try:
        for button in buttons:
            _focus(tk_root, button)
            assert _is_visible(frame, button), button.cget("text")
    finally:
        frame.destroy()


def test_content_that_fits_never_scrolls(tk_root: tk.Tk) -> None:
    frame, buttons = _frame_with_buttons(tk_root, count=3)
    try:
        assert not frame.has_scroll_overflow()
        _focus(tk_root, buttons[-1])
        assert frame._canvas.yview() == (0.0, 1.0)  # noqa: SLF001
    finally:
        frame.destroy()


def test_nested_frames_are_all_revealed(tk_root: tk.Tk) -> None:
    _show(tk_root)
    outer = ScrollableFrame(tk_root)
    outer.place(relx=0, rely=0, relwidth=1, relheight=1)
    for row in range(10):
        ttk.Label(outer.inner, text=f"filler {row}").grid(row=row, column=0, pady=12)
    inner_scroll = ScrollableFrame(outer.inner)
    inner_scroll.grid(row=10, column=0, sticky="ew")
    inner_scroll._canvas.configure(height=100)  # noqa: SLF001
    targets = [ttk.Button(inner_scroll.inner, text=f"Deep {row}") for row in range(20)]
    for row, button in enumerate(targets):
        button.grid(row=row, column=0, pady=2)
    tk_root.update_idletasks()
    tk_root.update()
    try:
        assert outer.has_scroll_overflow() and inner_scroll.has_scroll_overflow()
        _focus(tk_root, targets[-1])
        assert _is_visible(inner_scroll, targets[-1])
        assert outer._canvas.yview()[0] > 0  # noqa: SLF001
    finally:
        outer.destroy()


def test_the_router_still_removes_every_binding_it_added(tk_root: tk.Tk) -> None:
    before = {
        seq: str(tk_root.tk.call("bind", "all", seq)) for seq in ("<FocusIn>", "<MouseWheel>")
    }
    frame = ScrollableFrame(tk_root)
    try:
        router = _WheelRouter.for_widget(frame)
        assert router.installed
        assert "<FocusIn>" in router._funcids  # noqa: SLF001
    finally:
        frame.destroy()
    after = {seq: str(tk_root.tk.call("bind", "all", seq)) for seq in ("<FocusIn>", "<MouseWheel>")}
    assert after == before, (
        "destroying the last frame must leave other global bindings exactly as they were"
    )
