from __future__ import annotations

import pytest


def test_apply_theme_sets_styles():
    try:
        import tkinter as tk
    except Exception as exc:  # pragma: no cover - Tk may be unavailable
        pytest.skip(f"Tk not available: {exc}")

    from src.gui.theme_v2 import apply_theme

    root = tk.Tk()
    try:
        apply_theme(root)
        import tkinter.ttk as ttk

        style = ttk.Style(master=root)
        # Ensure key styles exist
        assert style.lookup("Primary.TButton", "background") != ""
        assert style.lookup("Panel.TFrame", "background") != ""
        assert style.lookup("StatusBar.TFrame", "background") != ""
    finally:
        root.destroy()
