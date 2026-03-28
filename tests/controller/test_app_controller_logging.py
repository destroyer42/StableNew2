from __future__ import annotations

from types import SimpleNamespace

from src.controller.app_controller import AppController


class _FakeLogWidget:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.seen = False

    def insert(self, _index: str, text: str) -> None:
        self.lines.append(text)

    def see(self, _index: str) -> None:
        self.seen = True


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
    log_widget = _FakeLogWidget()
    trace_panel = _FakeTracePanel()
    controller.main_window = SimpleNamespace(
        bottom_zone=SimpleNamespace(log_text=log_widget),
        log_trace_panel_v2=trace_panel,
    )

    controller._append_log("hello trace")

    assert log_widget.lines == ["hello trace\n"]
    assert log_widget.seen is True
    assert trace_panel.scheduled == 1
    assert trace_panel.refreshed == 0
