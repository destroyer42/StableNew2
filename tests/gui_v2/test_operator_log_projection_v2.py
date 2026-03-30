from __future__ import annotations

import tkinter as tk
from unittest.mock import patch

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


@pytest.mark.gui
def test_bottom_zone_operator_log_rollover_avoids_full_rebuild(tk_root: tk.Tk) -> None:
    state = AppStateV2()
    state.operator_log_max = 3
    window = MainWindowV2(tk_root, app_state=state)
    try:
        state.append_operator_log_line("alpha")
        state.append_operator_log_line("beta")
        state.append_operator_log_line("gamma")
        state.flush_now()
        tk_root.update()

        with patch.object(window.bottom_zone.log_text, "delete", wraps=window.bottom_zone.log_text.delete) as delete_spy:
            state.append_operator_log_line("delta")
            state.flush_now()
            tk_root.update()

        content = window.bottom_zone.log_text.get("1.0", "end")
        assert "alpha" not in content
        assert "beta" in content
        assert "gamma" in content
        assert "delta" in content
        assert not any(call.args == ("1.0", "end") for call in delete_spy.call_args_list)
    finally:
        try:
            window.cleanup()
        except Exception:
            pass


@pytest.mark.gui
def test_bottom_zone_skips_hidden_operator_log_projection_outside_test_mode(
    tk_root: tk.Tk,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = AppStateV2()
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("STABLENEW_TEST_MODE", "0")
    window = MainWindowV2(tk_root, app_state=state)
    try:
        state.append_operator_log_line("runtime-alpha")
        state.flush_now()
        tk_root.update()

        assert window.bottom_zone.log_text.get("1.0", "end").strip() == ""
        assert not window.bottom_zone._should_project_operator_log()
    finally:
        try:
            window.cleanup()
        except Exception:
            pass
