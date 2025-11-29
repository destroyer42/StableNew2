# Subsystem: Adapters
# Role: Routes controller/pipeline events into StatusBarV2 updates.

"""Tk-free adapter that maps controller callbacks to StatusBarV2 calls."""

from __future__ import annotations

from typing import Any


class StatusAdapterV2:
    """Map controller lifecycle/progress events to a StatusBarV2 instance."""

    def __init__(self, status_bar: Any) -> None:
        self._status_bar = status_bar

    def on_state_change(self, state: str | None) -> None:
        normalized = (state or "").lower()
        if normalized in ("idle",):
            self._status_bar.set_idle()
        elif normalized in ("running", "started", "busy"):
            self._status_bar.set_running()
        elif normalized in ("completed", "done", "success"):
            self._status_bar.set_completed()
        elif normalized in ("error", "failed"):
            self._status_bar.set_error()

    def on_progress(self, payload: dict[str, Any] | None) -> None:
        data = payload or {}
        percent = data.get("percent")
        eta_seconds = data.get("eta_seconds")
        try:
            fraction = float(percent) / 100.0
        except (TypeError, ValueError):
            fraction = None
        self._status_bar.update_progress(fraction)
        self._status_bar.update_eta(eta_seconds)
