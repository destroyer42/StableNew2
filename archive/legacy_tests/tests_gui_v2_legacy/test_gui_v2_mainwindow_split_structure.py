from __future__ import annotations

import pytest

from src.gui.main_window import StableNewGUI, enable_gui_test_mode, disable_gui_test_mode


def test_mainwindow_exposes_panel_attributes(monkeypatch):
    enable_gui_test_mode()
    try:
        gui = StableNewGUI()
    except Exception:
        disable_gui_test_mode()
        pytest.skip("Tkinter/Tcl not available")
    disable_gui_test_mode()
    assert hasattr(gui, "pipeline_panel_v2")
    assert hasattr(gui, "randomizer_panel_v2")
    assert hasattr(gui, "preview_panel_v2")
    assert hasattr(gui, "status_bar_v2")
    try:
        gui.root.destroy()
    except Exception:
        pass
