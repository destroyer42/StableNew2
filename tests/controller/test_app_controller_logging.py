from __future__ import annotations

from types import SimpleNamespace

from src.gui.app_state_v2 import AppStateV2
from src.controller.app_controller import AppController


class _FakeTracePanel:
    def __init__(self) -> None:
        self.scheduled = 0
        self.refreshed = 0

    def schedule_refresh_soon(self, delay_ms: int = 125) -> None:
        self.scheduled += 1

    def refresh(self) -> None:
        self.refreshed += 1


def test_append_log_schedules_trace_refresh_without_forcing_refresh() -> None:
    controller = AppController.__new__(AppController)
    controller.app_state = AppStateV2()
    trace_panel = _FakeTracePanel()
    controller.main_window = SimpleNamespace(
        log_trace_panel_v2=trace_panel,
    )

    controller._append_log("hello trace")

    assert controller.app_state.operator_log == ["hello trace"]
    assert trace_panel.scheduled == 1
    assert trace_panel.refreshed == 0
