from __future__ import annotations

import tkinter as tk

import pytest

from src.gui.app_state_v2 import AppStateV2
from src.gui.main_window_v2 import MainWindowV2


@pytest.mark.gui
def test_bottom_zone_projects_operator_log_from_app_state(tk_root: tk.Tk) -> None:
    state = AppStateV2()
    window = MainWindowV2(tk_root, app_state=state)
    try:
        state.append_operator_log_line("alpha")
        state.append_operator_log_line("beta")
        state.flush_now()
        tk_root.update()

        log_text = window.bottom_zone.log_text.get("1.0", "end")
        assert "alpha" in log_text
        assert "beta" in log_text

        state.clear_operator_log()
        state.flush_now()
        tk_root.update()

        assert window.bottom_zone.log_text.get("1.0", "end").strip() == ""
    finally:
        try:
            window.cleanup()
        except Exception:
            pass
