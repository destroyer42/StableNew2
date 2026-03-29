from __future__ import annotations

import pytest


def test_apply_theme_sets_styles():
    try:
        import tkinter as tk
    except Exception as exc:  # pragma: no cover - Tk may be unavailable
        pytest.skip(f"Tk not available: {exc}")

    from src.gui.theme_v2 import (
        ACCENT_GOLD,
        BACKGROUND_DARK,
        BACKGROUND_ELEVATED,
        BODY_LABEL_STYLE,
        CARD_FRAME_STYLE,
        PRIMARY_BUTTON_STYLE,
        apply_theme,
        apply_toplevel_theme,
        style_listbox_widget,
        style_text_widget,
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
        assert style.lookup("TLabel", "foreground") != ""
        assert style.lookup("TLabelframe", "background") != ""
        assert style.lookup("TSpinbox", "fieldbackground") != ""

        # Test new canonical styles
        assert style.lookup(CARD_FRAME_STYLE, "background") != ""
        assert style.lookup(BODY_LABEL_STYLE, "foreground") != ""
        assert style.lookup(PRIMARY_BUTTON_STYLE, "background") != ""

        dialog = tk.Toplevel(root)
        apply_toplevel_theme(dialog)
        assert dialog.cget("bg") == BACKGROUND_DARK

        text = tk.Text(dialog)
        style_text_widget(text, elevated=True)
        assert text.cget("bg") == BACKGROUND_ELEVATED
        assert text.cget("selectbackground") == ACCENT_GOLD

        listbox = tk.Listbox(dialog)
        style_listbox_widget(listbox)
        assert listbox.cget("bg") == BACKGROUND_ELEVATED
        assert listbox.cget("selectbackground") == ACCENT_GOLD
        dialog.destroy()
    finally:
        root.destroy()
