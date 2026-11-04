from __future__ import annotations

import tkinter as tk

import pytest

from src.gui.tooltip import attach_tooltip


def test_tooltip_helper_shows_and_hides():
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tkinter not available: {exc}")
    label = tk.Label(root, text="Test")
    label.pack()
    tooltip = attach_tooltip(label, "Helpful info", delay_ms=10)

    root.update_idletasks()
    root.deiconify()

    tooltip._show()
    assert tooltip._window is not None
    assert isinstance(tooltip._window, tk.Toplevel)
    tooltip._hide()
    assert tooltip._window is None
    root.destroy()


@pytest.fixture
def tooltip_root():
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tkinter not available: {exc}")
    root.withdraw()
    yield root
    try:
        root.destroy()
    except tk.TclError:
        pass


def _pending_afters(root: tk.Tk) -> set[str]:
    return {str(i) for i in root.tk.splitlist(root.tk.call("after", "info"))}


def test_hide_is_idempotent_and_cancels_the_pending_timer(tooltip_root):
    label = tk.Label(tooltip_root, text="Test")
    label.pack()
    tooltip = attach_tooltip(label, "Helpful info", delay_ms=60_000)

    tooltip._schedule(None)
    timer = tooltip._after_id
    assert timer in _pending_afters(tooltip_root)

    tooltip._hide()
    tooltip._hide()

    assert tooltip._after_id is None
    assert timer not in _pending_afters(tooltip_root)


def test_destroying_the_widget_cancels_the_timer_and_drops_the_popup(tooltip_root):
    label = tk.Label(tooltip_root, text="Test")
    label.pack()
    tooltip = attach_tooltip(label, "Helpful info", delay_ms=60_000)
    tooltip._schedule(None)
    timer = tooltip._after_id
    tooltip_root.update()
    tooltip._show()
    assert tooltip._window is not None

    label.destroy()
    tooltip_root.update()

    assert tooltip._window is None and tooltip._after_id is None
    assert timer not in _pending_afters(tooltip_root)


def test_a_late_timer_or_event_after_destruction_is_a_quiet_no_op(tooltip_root):
    label = tk.Label(tooltip_root, text="Test")
    label.pack()
    tooltip = attach_tooltip(label, "Helpful info", delay_ms=10)
    label.destroy()
    tooltip_root.update()

    tooltip._schedule(None)  # Enter delivered while the widget is going away
    tooltip._fire()  # a timer that was already running
    tooltip._show()
    tooltip._hide(None)

    assert tooltip._window is None and tooltip._after_id is None
    assert not [w for w in tooltip_root.winfo_children() if isinstance(w, tk.Toplevel)]


def test_firing_clears_the_timer_id_and_a_dead_popup_is_tolerated(tooltip_root):
    label = tk.Label(tooltip_root, text="Test")
    label.pack()
    tooltip = attach_tooltip(label, "Helpful info", delay_ms=10)
    tooltip._schedule(None)
    tooltip_root.update()
    tooltip_root.after(50, tooltip_root.quit)
    tooltip_root.mainloop()
    assert tooltip._after_id is None and tooltip._window is not None

    tooltip._window.destroy()  # destroyed behind the helper's back
    tooltip._hide()

    assert tooltip._window is None
