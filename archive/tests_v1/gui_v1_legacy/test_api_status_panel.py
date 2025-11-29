"""
Tests for APIStatusPanel component.
"""

import pytest

# Skip these tests if tkinter is not available
pytest.importorskip("tkinter")

import tkinter as tk
from tkinter import ttk

# Guard: skip cleanly if Tcl/Tk is not available (headless CI)
try:
    _tmp_root = tk.Tk()
    _tmp_root.destroy()
except tk.TclError:
    pytest.skip("Tk/Tcl unavailable in this environment", allow_module_level=True)

from src.gui.api_status_panel import APIStatusPanel
from tests.gui.conftest import create_tk_root


class TestAPIStatusPanel:
    """Test APIStatusPanel component."""

    def setup_method(self):
        """Set up test fixtures."""
        self.root = create_tk_root()
        self.root.withdraw()

    def teardown_method(self):
        """Clean up after tests."""
        try:
            self.root.destroy()
        except:
            pass

    def test_panel_creation(self):
        """Test that APIStatusPanel can be created."""
        panel = APIStatusPanel(self.root)
        assert panel is not None
        assert isinstance(panel, ttk.Frame)

    def test_set_status(self):
        """Test set_status method changes displayed text and color."""
        panel = APIStatusPanel(self.root)
        # Set status to Connected (green)
        panel.set_status("Connected", "green")
        self.root.update()  # Ensure after() events are processed
        assert panel.status_label.cget("text") == "Connected"
        # The color is set on status_indicator - convert to string for comparison
        fg_color = str(panel.status_indicator.cget("foreground"))
        assert fg_color in ("#4CAF50", "green", "#4caf50")
        # Set status to Error (red)
        panel.set_status("Error", "red")
        self.root.update()
        assert panel.status_label.cget("text") == "Error"
        fg_color = str(panel.status_indicator.cget("foreground"))
        assert fg_color in ("#f44336", "red", "#F44336")
        # Set connected status
        panel.set_status("Connected to API", "green")

        # We can't easily verify the actual text without accessing internals
        # but we can verify the method doesn't raise
        assert True

    def test_set_status_colors(self):
        """Test that different color statuses can be set."""
        panel = APIStatusPanel(self.root)

        # Test various colors
        panel.set_status("Connecting...", "yellow")
        panel.set_status("Connected", "green")
        panel.set_status("Disconnected", "red")
        panel.set_status("Error", "red")

        # Should not raise
        assert True

    def test_default_status(self):
        """Test that panel has a reasonable default status."""
        panel = APIStatusPanel(self.root)
        # Panel should be created successfully with default state
        assert panel is not None
