"""Tests for theme baseline functionality."""
import tkinter as tk

from src.gui.theme import (
    ASWF_BLACK,
    ASWF_DARK_GREY,
    ASWF_ERROR_RED,
    ASWF_GOLD,
    ASWF_LIGHT_GREY,
    ASWF_MED_GREY,
    ASWF_OK_GREEN,
    FONT_FAMILY,
    FONT_SIZE_BASE,
    FONT_SIZE_BUTTON,
    FONT_SIZE_HEADING,
    FONT_SIZE_LABEL,
    Theme,
)


class TestTheme:
    """Test the Theme class functionality."""

    def test_apply_root_sets_dark_background(self, tk_root):
        theme = Theme()
        theme.apply_root(tk_root)
        assert tk_root["bg"] == ASWF_BLACK

    def test_style_button_primary(self, tk_root):
        theme = Theme()
        button = tk.Button(tk_root, text="Test")

        theme.style_button_primary(button)

        assert button["bg"] == ASWF_GOLD
        assert button["fg"] == ASWF_BLACK
        assert "bold" in button["font"]
        assert button["relief"] == "flat"
        assert button["borderwidth"] == 0

    def test_style_button_danger(self, tk_root):
        theme = Theme()
        button = tk.Button(tk_root, text="Test")

        theme.style_button_danger(button)

        assert button["bg"] == ASWF_ERROR_RED
        assert button["fg"] == "white"
        assert button["relief"] == "flat"
        assert button["borderwidth"] == 0

    def test_style_frame(self, tk_root):
        theme = Theme()
        frame = tk.Frame(tk_root)

        theme.style_frame(frame)

        assert frame["bg"] == ASWF_DARK_GREY
        assert frame["relief"] == "flat"
        assert frame["borderwidth"] == 0

    def test_style_label(self, tk_root):
        theme = Theme()
        label = tk.Label(tk_root, text="Test")

        theme.style_label(label)

        assert label["bg"] == ASWF_DARK_GREY
        assert label["fg"] == ASWF_GOLD
        assert FONT_FAMILY in label["font"]

    def test_style_label_heading(self, tk_root):
        theme = Theme()
        label = tk.Label(tk_root, text="Test")

        theme.style_label_heading(label)

        assert label["bg"] == ASWF_DARK_GREY
        assert label["fg"] == ASWF_GOLD
        assert "bold" in label["font"]

    def test_style_entry(self, tk_root):
        theme = Theme()
        entry = tk.Entry(tk_root)

        theme.style_entry(entry)

        assert entry["bg"] == ASWF_MED_GREY
        assert entry["fg"] == "white"
        assert entry["insertbackground"] == ASWF_GOLD
        assert entry["relief"] == "flat"
        assert entry["borderwidth"] == 1

    def test_style_text(self, tk_root):
        theme = Theme()
        text_widget = tk.Text(tk_root)

        theme.style_text(text_widget)

        assert text_widget["bg"] == ASWF_MED_GREY
        assert text_widget["fg"] == ASWF_LIGHT_GREY
        assert text_widget["insertbackground"] == ASWF_GOLD
        assert text_widget["relief"] == "flat"
        assert text_widget["borderwidth"] == 1

    def test_style_listbox(self, tk_root):
        theme = Theme()
        listbox = tk.Listbox(tk_root)

        theme.style_listbox(listbox)

        assert listbox["bg"] == ASWF_MED_GREY
        assert listbox["fg"] == "white"
        assert listbox["selectbackground"] == ASWF_GOLD
        assert listbox["selectforeground"] == ASWF_BLACK
        assert listbox["relief"] == "flat"
        assert listbox["borderwidth"] == 1

    def test_style_scrollbar(self, tk_root):
        theme = Theme()
        scrollbar = tk.Scrollbar(tk_root)

        theme.style_scrollbar(scrollbar)

        assert scrollbar["bg"] == ASWF_MED_GREY
        assert scrollbar["troughcolor"] == ASWF_DARK_GREY
        assert scrollbar["relief"] == "flat"
        assert scrollbar["borderwidth"] == "1"


class TestThemeConstants:
    """Test theme constant values."""

    def test_aswf_colors_defined(self):
        """Test that all ASWF colors are properly defined."""
        assert ASWF_BLACK == "#221F20"
        assert ASWF_GOLD == "#FFC805"
        assert ASWF_DARK_GREY == "#2B2A2C"
        assert ASWF_MED_GREY == "#3A393D"
        assert ASWF_LIGHT_GREY == "#4A4950"
        assert ASWF_ERROR_RED == "#CC3344"
        assert ASWF_OK_GREEN == "#44AA55"

    def test_font_constants_defined(self):
        """Test that font constants are properly defined."""
        assert FONT_FAMILY == "Calibri"
        assert FONT_SIZE_BASE == 11  # Updated for consistency
        assert FONT_SIZE_LABEL == 11
        assert FONT_SIZE_BUTTON == 11
        assert FONT_SIZE_HEADING == 13
