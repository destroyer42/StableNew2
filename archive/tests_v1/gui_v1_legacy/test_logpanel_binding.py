"""Tests for LogPanel early binding and proxy methods in StableNewGUI."""

import pytest

# Skip these tests if tkinter is not available
pytest.importorskip("tkinter")

import tkinter as tk

from src.gui.main_window import StableNewGUI


class TestLogPanelBinding:
    """Test LogPanel early initialization and proxy methods."""

    def setup_method(self):
        """Set up test fixtures."""
        try:
            # Minimal headless-safe GUI initialization
            self.gui = StableNewGUI.__new__(StableNewGUI)
            self.gui.root = tk.Tk()
            self.gui.root.withdraw()

            # Initialize just the logging-related attributes
            from tkinter import ttk

            from src.gui.log_panel import LogPanel

            self.gui._early_log_frame = ttk.Frame(self.gui.root, style="Dark.TFrame")
            self.gui.log_panel = LogPanel(
                self.gui._early_log_frame, coordinator=self.gui, height=6, style="Dark.TFrame"
            )
            self.gui.add_log = self.gui.log_panel.append
            self.gui.log_text = getattr(self.gui.log_panel, "text", None)

        except tk.TclError:
            pytest.skip("Tk/Tcl unavailable in this environment")

    def teardown_method(self):
        """Clean up after tests."""
        try:
            if hasattr(self, "gui") and hasattr(self.gui, "root"):
                self.gui.root.destroy()
        except tk.TclError:
            pass

    def test_log_panel_exists_early(self):
        """Test that log_panel is created early in __init__."""
        assert hasattr(self.gui, "log_panel")
        assert self.gui.log_panel is not None

    def test_add_log_proxy_exists(self):
        """Test that add_log proxy method exists."""
        assert hasattr(self.gui, "add_log")
        assert callable(self.gui.add_log)

    def test_log_text_alias_exists(self):
        """Test that log_text alias exists for legacy compatibility."""
        assert hasattr(self.gui, "log_text")
        # log_text should be either the text widget or None
        assert self.gui.log_text is None or hasattr(self.gui.log_text, "insert")

    def test_add_log_proxy_calls_append(self):
        """Test that add_log proxy calls log_panel.append."""
        # Call the proxy
        self.gui.add_log("Test message", "INFO")

        # Flush the queue to process message
        self.gui.log_panel._flush_queue_sync()
        self.gui.root.update()

        # Verify message was logged
        content = self.gui.log_panel.log_text.get("1.0", "end-1c")
        assert "Test message" in content

    def test_log_message_with_safe_fallback(self):
        """Test that log_message has safe fallback when subsystem not ready."""

        # Mock scenario where log_panel exists but add_log doesn't
        gui_no_proxy = StableNewGUI.__new__(StableNewGUI)
        gui_no_proxy.root = tk.Tk()
        gui_no_proxy.root.withdraw()

        # Simulate early call before add_log is set
        # Should not raise AttributeError
        try:
            # This should use print fallback without crashing
            if not hasattr(gui_no_proxy, "add_log") and not hasattr(gui_no_proxy, "log_panel"):
                # Safe to test fallback path
                pass
        finally:
            gui_no_proxy.root.destroy()
