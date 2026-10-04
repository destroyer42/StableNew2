"""PR-RUNTIME-WEBUI-WATCHDOG-120: the watchdog is attached only after the Tk heartbeat exists."""

from __future__ import annotations

import pytest

from src.app_factory import build_v2_app
from src.controller.app_controller import AppController
from src.gui.main_window_v2 import MainWindowV2


@pytest.mark.gui
def test_watchdog_attaches_once_after_the_heartbeat_source_is_installed(monkeypatch) -> None:
    events: list[str] = []
    attach_states: list[dict[str, object]] = []

    original_install = MainWindowV2._install_ui_heartbeat

    def spy_install(self, *args, **kwargs):
        events.append("heartbeat-installed")
        return original_install(self, *args, **kwargs)

    def spy_attach(self, diagnostics_service):
        events.append("watchdog-attached")
        attach_states.append(
            {
                "window_present": getattr(self, "main_window", None) is not None,
                "diagnostics_service": diagnostics_service,
            }
        )
        # Record only: the real watchdog thread is not needed to prove ordering.

    monkeypatch.setattr(MainWindowV2, "_install_ui_heartbeat", spy_install)
    monkeypatch.setattr(AppController, "attach_watchdog", spy_attach)

    try:
        root, _, controller, window = build_v2_app()
    except Exception as exc:  # pragma: no cover - Tk unavailable
        pytest.skip(f"Tkinter not available: {exc}")
        return

    try:
        assert events == ["heartbeat-installed", "watchdog-attached"]
        assert len(attach_states) == 1
        assert attach_states[0]["window_present"] is True
        assert attach_states[0]["diagnostics_service"] is not None
        assert controller.main_window is window
    finally:
        try:
            root.destroy()
        except Exception:
            pass
