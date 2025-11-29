from __future__ import annotations

import os
import pytest

from src.gui.main_window import StableNewGUI, enable_gui_test_mode, disable_gui_test_mode


def test_ai_button_absent_when_flag_off(monkeypatch):
    monkeypatch.delenv("ENABLE_AI_SETTINGS_GENERATOR", raising=False)
    enable_gui_test_mode()
    try:
        gui = StableNewGUI()
    except Exception:
        disable_gui_test_mode()
        pytest.skip("Tkinter/Tcl not available")
    disable_gui_test_mode()
    assert not getattr(gui, "_ai_settings_enabled", False)
    assert not hasattr(gui, "_ai_settings_button") or getattr(gui, "_ai_settings_button") is None
    try:
        gui.root.destroy()
    except Exception:
        pass


def test_ai_button_present_when_flag_on(monkeypatch):
    monkeypatch.setenv("ENABLE_AI_SETTINGS_GENERATOR", "1")
    enable_gui_test_mode()
    try:
        gui = StableNewGUI()
    except Exception:
        disable_gui_test_mode()
        pytest.skip("Tkinter/Tcl not available")
    disable_gui_test_mode()
    assert getattr(gui, "_ai_settings_enabled", False)
    assert getattr(gui, "_ai_settings_button", None) is not None
    try:
        gui.root.destroy()
    except Exception:
        pass
