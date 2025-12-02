from __future__ import annotations

from src.gui_v2.adapters.status_adapter_v2 import StatusAdapterV2


class _FakeStatusBar:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def set_idle(self) -> None:
        self.calls.append(("idle", None))

    def set_running(self) -> None:
        self.calls.append(("running", None))

    def set_completed(self) -> None:
        self.calls.append(("completed", None))

    def set_error(self, message: str | None = None) -> None:
        self.calls.append(("error", message))

    def update_progress(self, fraction: float | None) -> None:
        self.calls.append(("progress", fraction))

    def update_eta(self, seconds: float | None) -> None:
        self.calls.append(("eta", seconds))


def test_status_adapter_maps_state_changes() -> None:
    bar = _FakeStatusBar()
    adapter = StatusAdapterV2(bar)

    adapter.on_state_change("running")
    adapter.on_state_change("completed")
    adapter.on_state_change("error")
    adapter.on_state_change("idle")

    assert ("running", None) in bar.calls
    assert ("completed", None) in bar.calls
    assert ("error", None) in bar.calls
    assert ("idle", None) in bar.calls


def test_status_adapter_maps_progress_payload() -> None:
    bar = _FakeStatusBar()
    adapter = StatusAdapterV2(bar)

    adapter.on_progress({"percent": 50, "eta_seconds": 30})

    assert ("progress", 0.5) in bar.calls
    assert ("eta", 30) in bar.calls
