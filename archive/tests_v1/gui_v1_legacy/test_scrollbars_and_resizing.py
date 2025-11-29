"""Tests for PR-2 scrollbars and resizing behavior."""

import tkinter as tk

from src.gui.main_window import StableNewGUI


class TestScrollbarsAndResizing:
    def test_scrollable_sections_and_minsize(self, tk_root):
        gui = StableNewGUI(root=tk_root)

        # Minimum size enforced
        assert getattr(gui, "window_min_size", None) == (1024, 720)

        expected_sections = {"pipeline", "randomization", "general"}
        assert expected_sections.issubset(gui.scrollable_sections.keys())

        tab_index = {"pipeline": 0, "randomization": 1, "general": 2}

        gui.root.geometry("800x600")

        for name in expected_sections:
            gui.center_notebook.select(tab_index[name])
            gui.root.update_idletasks()
            section = gui.scrollable_sections[name]
            scrollbar = section.get("scrollbar")
            assert scrollbar is not None, f"{name} missing scrollbar reference"
            assert isinstance(scrollbar, tk.Widget)
            assert scrollbar.winfo_exists()
