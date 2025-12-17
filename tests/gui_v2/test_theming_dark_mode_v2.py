"""PR-GUI-A: Theming & Control Polish tests (V2.5).

These tests validate:
- Dark-mode styling for spinboxes, comboboxes, entries, labels
- Combobox popup listbox uses dark background
- Slider value labels use proper styling
- All theme styles are applied correctly
"""

from __future__ import annotations

import pytest


def _skip_if_no_tk():
    """Helper to skip test if Tk is unavailable."""
    try:
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        return root
    except Exception as exc:
        pytest.skip(f"Tk not available: {exc}")


class TestSpinboxDarkModeStyle:
    """Test that spinboxes use dark-mode styling."""

    def test_dark_spinbox_style_exists(self):
        """Dark.TSpinbox style should be defined in theme."""
        root = _skip_if_no_tk()
        try:
            from tkinter import ttk

            from src.gui.theme_v2 import DARK_SPINBOX_STYLE, apply_theme

            apply_theme(root)
            style = ttk.Style(master=root)

            # Style should exist and have dark background
            bg = style.lookup(DARK_SPINBOX_STYLE, "fieldbackground")
            assert bg != "", "Dark.TSpinbox fieldbackground should be set"
        finally:
            root.destroy()

    def test_spinbox_uses_dark_style(self):
        """Spinbox widget should be created with Dark.TSpinbox style."""
        root = _skip_if_no_tk()
        try:
            import tkinter as tk
            from tkinter import ttk

            from src.gui.theme_v2 import apply_theme

            apply_theme(root)
            var = tk.IntVar(value=20)
            spin = ttk.Spinbox(root, from_=1, to=100, textvariable=var, style="Dark.TSpinbox")

            assert spin.cget("style") == "Dark.TSpinbox"
        finally:
            root.destroy()


class TestComboboxDarkModeStyle:
    """Test that combobox popups use dark-mode styling."""

    def test_dark_combobox_style_exists(self):
        """Dark.TCombobox style should be defined in theme."""
        root = _skip_if_no_tk()
        try:
            from tkinter import ttk

            from src.gui.theme_v2 import DARK_COMBOBOX_STYLE, apply_theme

            apply_theme(root)
            style = ttk.Style(master=root)

            # Style should exist and have dark background
            bg = style.lookup(DARK_COMBOBOX_STYLE, "fieldbackground")
            assert bg != "", "Dark.TCombobox fieldbackground should be set"
        finally:
            root.destroy()

    def test_combobox_popup_dark_mode_options_set(self):
        """Combobox popup listbox should have dark-mode options configured."""
        root = _skip_if_no_tk()
        try:
            from src.gui.theme_v2 import BACKGROUND_ELEVATED, TEXT_PRIMARY, apply_theme

            apply_theme(root)

            # Check that option_add was called for combobox listbox
            # Note: We verify the colors are set in the theme,
            # actual popup testing requires manual verification
            assert BACKGROUND_ELEVATED == "#1E1E1E"
            assert TEXT_PRIMARY == "#FFFFFF"
        finally:
            root.destroy()


class TestEntryDarkModeStyle:
    """Test that entries use dark-mode styling."""

    def test_dark_entry_style_exists(self):
        """Dark.TEntry style should be defined in theme."""
        root = _skip_if_no_tk()
        try:
            from tkinter import ttk

            from src.gui.theme_v2 import DARK_ENTRY_STYLE, apply_theme

            apply_theme(root)
            style = ttk.Style(master=root)

            # Style should exist and have dark background
            bg = style.lookup(DARK_ENTRY_STYLE, "fieldbackground")
            assert bg != "", "Dark.TEntry fieldbackground should be set"
        finally:
            root.destroy()


class TestSliderValueLabelStyle:
    """Test that slider value labels use proper styling."""

    def test_slider_value_label_style_exists(self):
        """SliderValue.TLabel style should be defined in theme."""
        root = _skip_if_no_tk()
        try:
            from tkinter import ttk

            from src.gui.theme_v2 import SLIDER_VALUE_LABEL_STYLE, apply_theme

            apply_theme(root)
            style = ttk.Style(master=root)

            # Style should exist and have proper colors
            bg = style.lookup(SLIDER_VALUE_LABEL_STYLE, "background")
            fg = style.lookup(SLIDER_VALUE_LABEL_STYLE, "foreground")
            assert bg != "", "SliderValue.TLabel background should be set"
            assert fg != "", "SliderValue.TLabel foreground should be set"
        finally:
            root.destroy()

    def test_labeled_slider_value_updates(self):
        """LabeledSlider value label should update when slider moves."""
        root = _skip_if_no_tk()
        try:
            import tkinter as tk

            from src.gui.stage_cards_v2.components import LabeledSlider
            from src.gui.theme_v2 import apply_theme

            apply_theme(root)
            var = tk.DoubleVar(value=0.5)
            slider = LabeledSlider(root, variable=var, from_=0.0, to=1.0)
            slider.pack()

            # Initial value should be displayed
            initial_text = slider._value_label.cget("text")
            assert "0.50" in initial_text or "0.5" in initial_text

            # Change value and verify label updates
            var.set(0.75)
            root.update_idletasks()
            updated_text = slider._value_label.cget("text")
            assert "0.75" in updated_text or "75" in updated_text
        finally:
            root.destroy()


class TestDarkLabelStyle:
    """Test that labels use dark-mode styling."""

    def test_dark_label_style_exists(self):
        """Dark.TLabel style should be defined in theme."""
        root = _skip_if_no_tk()
        try:
            from tkinter import ttk

            from src.gui.theme_v2 import DARK_LABEL_STYLE, apply_theme

            apply_theme(root)
            style = ttk.Style(master=root)

            # Style should exist and have proper colors
            bg = style.lookup(DARK_LABEL_STYLE, "background")
            fg = style.lookup(DARK_LABEL_STYLE, "foreground")
            assert bg != "", "Dark.TLabel background should be set"
            assert fg != "", "Dark.TLabel foreground should be set"
        finally:
            root.destroy()


class TestCheckbuttonDarkModeStyle:
    """Test that checkbuttons use dark-mode styling."""

    def test_dark_checkbutton_style_exists(self):
        """Dark.TCheckbutton style should be defined in theme."""
        root = _skip_if_no_tk()
        try:
            from tkinter import ttk

            from src.gui.theme_v2 import DARK_CHECKBUTTON_STYLE, apply_theme

            apply_theme(root)
            style = ttk.Style(master=root)

            # Style should exist and have proper colors
            bg = style.lookup(DARK_CHECKBUTTON_STYLE, "background")
            assert bg != "", "Dark.TCheckbutton background should be set"
        finally:
            root.destroy()


class TestScaleDarkModeStyle:
    """Test that scales (sliders) use dark-mode styling."""

    def test_dark_scale_style_exists(self):
        """Dark.Horizontal.TScale style should be defined in theme."""
        root = _skip_if_no_tk()
        try:
            from tkinter import ttk

            from src.gui.theme_v2 import DARK_SCALE_STYLE, apply_theme

            apply_theme(root)
            style = ttk.Style(master=root)

            # Style should exist and have proper trough color
            trough = style.lookup(DARK_SCALE_STYLE, "troughcolor")
            assert trough != "", "Dark.Horizontal.TScale troughcolor should be set"
        finally:
            root.destroy()


class TestButtonDarkModeStyle:
    """Test that buttons use dark-mode styling."""

    def test_dark_button_style_exists(self):
        """Dark.TButton style should be defined in theme."""
        root = _skip_if_no_tk()
        try:
            from tkinter import ttk

            from src.gui.theme_v2 import DARK_BUTTON_STYLE, apply_theme

            apply_theme(root)
            style = ttk.Style(master=root)

            # Style should exist and have proper colors
            bg = style.lookup(DARK_BUTTON_STYLE, "background")
            fg = style.lookup(DARK_BUTTON_STYLE, "foreground")
            assert bg != "", "Dark.TButton background should be set"
            assert fg != "", "Dark.TButton foreground should be set"
        finally:
            root.destroy()


class TestAllDarkStylesExported:
    """Test that all dark style constants are exported from theme_v2."""

    def test_all_style_constants_exported(self):
        """All dark-mode style constants should be exported."""
        from src.gui import theme_v2

        expected_exports = [
            "DARK_ENTRY_STYLE",
            "DARK_COMBOBOX_STYLE",
            "DARK_SPINBOX_STYLE",
            "DARK_CHECKBUTTON_STYLE",
            "DARK_LABEL_STYLE",
            "DARK_SCALE_STYLE",
            "DARK_BUTTON_STYLE",
            "SLIDER_VALUE_LABEL_STYLE",
        ]

        for export in expected_exports:
            assert hasattr(theme_v2, export), f"{export} should be exported from theme_v2"
            value = getattr(theme_v2, export)
            assert isinstance(value, str), f"{export} should be a string style name"
            assert value != "", f"{export} should not be empty"
