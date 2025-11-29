from __future__ import annotations

import tkinter as tk
import pytest

from src.gui.scrolling import enable_mousewheel, make_scrollable


def test_scrolling_helper_creates_container():
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tkinter not available: {exc}")

    container, inner = make_scrollable(root)
    container.pack()
    inner.pack()
    enable_mousewheel(inner)
    root.update_idletasks()
    assert container.winfo_exists()
    assert inner.winfo_exists()
    root.destroy()
