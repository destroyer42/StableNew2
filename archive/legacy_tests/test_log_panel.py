"""Tests for LogPanel behaviors such as scrolling, filters, and clipboard."""

from src.gui.log_panel import LogPanel


def test_log_appends_to_widget_and_scrolls(tk_root, tk_pump):
    """Test that log() appends messages and keeps view at bottom by default."""
    panel = LogPanel(tk_root, height=3)

    for i in range(20):
        panel.log(f"Message {i+1}", "INFO")

    tk_pump()

    log_content = panel.log_text.get("1.0", "end-1c")
    assert "Message 1" in log_content
    assert "Message 20" in log_content

    yview = panel.log_text.yview()
    assert yview[1] >= 0.9, f"Not scrolled near bottom: yview={yview}"


def test_scroll_lock_prevents_auto_scroll(tk_root, tk_pump):
    """Enabling scroll lock should prevent auto-scrolling on new messages."""
    panel = LogPanel(tk_root, height=4)

    for i in range(10):
        panel.log(f"Initial {i}", "INFO")

    tk_pump()

    panel.scroll_lock_var.set(True)
    panel._on_scroll_lock_toggle()

    panel.log_text.yview_moveto(0.0)

    panel.log("Locked message", "INFO")

    tk_pump()

    yview = panel.log_text.yview()
    assert yview[1] < 0.9, "Scroll lock should keep the view away from the bottom"


def test_level_filter_hides_and_restores_messages(tk_root, tk_pump):
    """Disabling a level filter hides messages and re-enabling shows them again."""
    panel = LogPanel(tk_root)

    panel.log("Info visible", "INFO")
    panel.log("Error visible", "ERROR")

    tk_pump()

    content = panel.log_text.get("1.0", "end-1c")
    assert "Info visible" in content
    assert "Error visible" in content

    panel.level_filter_vars["INFO"].set(False)
    panel._on_filter_change()

    tk_pump(0.1)

    filtered_content = panel.log_text.get("1.0", "end-1c")
    assert "Info visible" not in filtered_content
    assert "Error visible" in filtered_content

    panel.level_filter_vars["INFO"].set(True)
    panel._on_filter_change()

    tk_pump(0.1)

    restored_content = panel.log_text.get("1.0", "end-1c")
    assert "Info visible" in restored_content
