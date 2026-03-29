from __future__ import annotations

import tkinter as tk

import pytest

from src.gui.views.pipeline_tab_frame_v2 import PipelineTabFrame
from tests.helpers.gui_harness_v2 import GuiV2Harness


class _FakeDiagnosticsPanel:
    def __init__(self, name: str) -> None:
        self._name = name

    def get_diagnostics_snapshot(self) -> dict[str, object]:
        return {"panel": self._name}


class _FakeQueuePanel(_FakeDiagnosticsPanel):
    def __init__(self) -> None:
        super().__init__("queue")
        self.update_calls = 0
        self.mapped = True

    def update_from_app_state(self, app_state) -> None:  # noqa: ANN001 - test double
        self.update_calls += 1

    def winfo_ismapped(self) -> bool:
        return self.mapped


class _FakeRunningPanel(_FakeDiagnosticsPanel):
    def __init__(self) -> None:
        super().__init__("running")
        self.update_calls = 0
        self.mapped = True

    def update_from_app_state(self, app_state) -> None:  # noqa: ANN001 - test double
        self.update_calls += 1

    def winfo_ismapped(self) -> bool:
        return self.mapped


class _FakeHistoryPanel(_FakeDiagnosticsPanel):
    def __init__(self) -> None:
        super().__init__("history")
        self.update_calls = 0
        self.mapped = True

    def update_from_app_state(self, app_state) -> None:  # noqa: ANN001 - test double
        self.update_calls += 1

    def winfo_ismapped(self) -> bool:
        return self.mapped


class _FakePreviewPanel(_FakeDiagnosticsPanel):
    def __init__(self) -> None:
        super().__init__("preview")
        self.preview_calls = 0
        self.app_state_calls = 0
        self.draft_calls = 0
        self.mapped = True

    def set_preview_jobs(self, jobs) -> None:  # noqa: ANN001 - test double
        self.preview_calls += 1

    def update_from_job_draft(self, job_draft) -> None:  # noqa: ANN001 - test double
        self.draft_calls += 1

    def update_from_app_state(self, app_state) -> None:  # noqa: ANN001 - test double
        self.app_state_calls += 1

    def winfo_ismapped(self) -> bool:
        return self.mapped


def test_pipeline_tab_callback_metrics_snapshot_tracks_counts_and_slow_calls() -> None:
    tab = PipelineTabFrame.__new__(PipelineTabFrame)
    tab._callback_metrics = {}
    tab._hot_surface_dirty = set()
    tab._hot_surface_flush_scheduled = False
    tab._hot_surface_flush_metrics = {
        "count": 0,
        "total_ms": 0.0,
        "max_ms": 0.0,
        "last_ms": 0.0,
        "slow_count": 0,
    }
    tab.queue_panel = _FakeDiagnosticsPanel("queue")
    tab.history_panel = _FakeDiagnosticsPanel("history")
    tab.preview_panel = _FakeDiagnosticsPanel("preview")

    tab._record_callback_metric("_on_runtime_status_changed", 5.0)
    tab._record_callback_metric("_on_runtime_status_changed", 25.0)

    snapshot = tab.get_diagnostics_snapshot()
    metrics = snapshot["callback_metrics"]["_on_runtime_status_changed"]

    assert snapshot["slow_threshold_ms"] == PipelineTabFrame.SLOW_UPDATE_THRESHOLD_MS
    assert metrics["count"] == 2
    assert metrics["avg_ms"] == 15.0
    assert metrics["max_ms"] == 25.0
    assert metrics["last_ms"] == 25.0
    assert metrics["slow_count"] == 1
    assert snapshot["hot_surface_scheduler"]["count"] == 0
    assert snapshot["queue_panel"] == {"panel": "queue"}
    assert snapshot["history_panel"] == {"panel": "history"}
    assert snapshot["preview_panel"] == {"panel": "preview"}


def test_pipeline_tab_hot_surface_scheduler_coalesces_dirty_updates() -> None:
    tab = PipelineTabFrame.__new__(PipelineTabFrame)
    tab.app_state = type("State", (), {"preview_jobs": ["job-1"], "job_draft": object()})()
    tab.queue_panel = _FakeQueuePanel()
    tab.running_job_panel = _FakeRunningPanel()
    tab.history_panel = _FakeHistoryPanel()
    tab.preview_panel = _FakePreviewPanel()
    tab._hot_surface_dirty = set()
    tab._hot_surface_flush_scheduled = False
    tab._hot_surface_flush_metrics = {
        "count": 0,
        "total_ms": 0.0,
        "max_ms": 0.0,
        "last_ms": 0.0,
        "slow_count": 0,
    }
    scheduled: list[tuple[int, object]] = []
    tab.after = lambda delay_ms, fn: scheduled.append((delay_ms, fn))  # type: ignore[method-assign]

    tab._mark_hot_surface_dirty("queue")
    tab._mark_hot_surface_dirty("running", "history", "preview")

    assert len(scheduled) == 1
    assert scheduled[0][0] == PipelineTabFrame.HOT_SURFACE_FLUSH_DELAY_MS

    flush = scheduled[0][1]
    assert callable(flush)
    flush()

    assert tab.queue_panel.update_calls == 1
    assert tab.running_job_panel.update_calls == 1
    assert tab.history_panel.update_calls == 1
    assert tab.preview_panel.preview_calls == 1
    assert tab.preview_panel.draft_calls == 0
    assert tab.preview_panel.app_state_calls == 1
    assert tab._hot_surface_flush_metrics["count"] == 1


def test_pipeline_tab_defers_hidden_hot_surfaces_until_visible() -> None:
    tab = PipelineTabFrame.__new__(PipelineTabFrame)
    tab.app_state = type("State", (), {"preview_jobs": ["job-1"], "job_draft": object()})()
    tab.queue_panel = _FakeQueuePanel()
    tab.running_job_panel = _FakeRunningPanel()
    tab.history_panel = _FakeHistoryPanel()
    tab.preview_panel = _FakePreviewPanel()
    tab.preview_panel.mapped = False
    tab._hot_surface_dirty = set()
    tab._hot_surface_flush_scheduled = False
    tab._hot_surface_flush_metrics = {
        "count": 0,
        "total_ms": 0.0,
        "max_ms": 0.0,
        "last_ms": 0.0,
        "slow_count": 0,
    }
    tab._width_ensured = True
    scheduled: list[tuple[int, object]] = []
    tab.after = lambda delay_ms, fn: scheduled.append((delay_ms, fn))  # type: ignore[method-assign]

    tab._mark_hot_surface_dirty("preview")
    assert len(scheduled) == 1
    flush = scheduled.pop()[1]
    assert callable(flush)
    flush()

    assert tab.preview_panel.preview_calls == 0
    assert tab.preview_panel.app_state_calls == 0
    assert tab._hot_surface_dirty == {"preview"}
    assert tab._hot_surface_flush_scheduled is False

    tab.preview_panel.mapped = True
    tab._on_first_map()

    assert len(scheduled) == 1
    resumed_flush = scheduled.pop()[1]
    assert callable(resumed_flush)
    resumed_flush()

    assert tab.preview_panel.preview_calls == 1
    assert tab.preview_panel.app_state_calls == 1
    assert tab._hot_surface_dirty == set()


@pytest.mark.gui
def test_pipeline_tab_owns_hot_surface_subscriptions(tk_root: tk.Tk) -> None:
    harness = GuiV2Harness(tk_root)
    try:
        state = harness.window.app_state

        preview_listeners = list(state._listeners.get("preview_jobs", []))
        history_listeners = list(state._listeners.get("history_items", []))
        queue_job_listeners = list(state._listeners.get("queue_jobs", []))

        assert any(getattr(listener, "__self__", None) is harness.pipeline_tab for listener in preview_listeners)
        assert all(
            type(getattr(listener, "__self__", None)).__name__ != "PreviewPanelV2"
            for listener in preview_listeners
        )

        assert any(getattr(listener, "__self__", None) is harness.pipeline_tab for listener in history_listeners)
        assert all(
            type(getattr(listener, "__self__", None)).__name__ != "JobHistoryPanelV2"
            for listener in history_listeners
        )

        assert any(getattr(listener, "__self__", None) is harness.pipeline_tab for listener in queue_job_listeners)
        assert all(
            type(getattr(listener, "__self__", None)).__name__ != "QueuePanelV2"
            for listener in queue_job_listeners
        )
    finally:
        harness.cleanup()
