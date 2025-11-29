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

    tooltip._show()
    assert tooltip._window is not None
    assert isinstance(tooltip._window, tk.Toplevel)
    tooltip._hide()
    assert tooltip._window is None
    root.destroy()
