"""Tests for APIStatusPanel set_status method.
Created: 2025-11-02 22:31:47
Updated: 2025-11-04
"""

from src.gui.api_status_panel import APIStatusPanel


def test_api_status_sets_text_and_color(tk_root):
    """Test that set_status updates both text and color indicator."""
    panel = APIStatusPanel(tk_root)

    # Test green status
    panel.set_status("Connected to API", "green")
    tk_root.update()
    assert panel.status_label.cget("text") == "Connected to API"
    fg_color = str(panel.status_indicator.cget("foreground"))
    assert fg_color in ("#4CAF50", "#4caf50", "green")

    # Test red status
    panel.set_status("Connection failed", "red")
    tk_root.update()
    assert panel.status_label.cget("text") == "Connection failed"
    fg_color = str(panel.status_indicator.cget("foreground"))
    assert fg_color in ("#f44336", "#F44336", "red")

    # Test yellow status
    panel.set_status("Connecting...", "yellow")
    tk_root.update()
    assert panel.status_label.cget("text") == "Connecting..."
    fg_color = str(panel.status_indicator.cget("foreground"))
    assert fg_color in ("#FF9800", "#ff9800", "yellow")
