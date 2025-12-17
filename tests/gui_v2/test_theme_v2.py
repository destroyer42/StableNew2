from __future__ import annotations

import pytest


def test_apply_theme_sets_styles():
    try:
        import tkinter as tk
    except Exception as exc:  # pragma: no cover - Tk may be unavailable
        pytest.skip(f"Tk not available: {exc}")

    from src.gui.theme_v2 import (
        BODY_LABEL_STYLE,
        CARD_FRAME_STYLE,
        PRIMARY_BUTTON_STYLE,
        apply_theme,
    )

    root = tk.Tk()
    try:
        apply_theme(root)
        import tkinter.ttk as ttk

        style = ttk.Style(master=root)
        # Ensure key styles exist
        assert style.lookup("Primary.TButton", "background") != ""
        assert style.lookup("Panel.TFrame", "background") != ""
        assert style.lookup("StatusBar.TFrame", "background") != ""

        # Test new canonical styles
        assert style.lookup(CARD_FRAME_STYLE, "background") != ""
        assert style.lookup(BODY_LABEL_STYLE, "foreground") != ""
        assert style.lookup(PRIMARY_BUTTON_STYLE, "background") != ""
    finally:
        root.destroy()
