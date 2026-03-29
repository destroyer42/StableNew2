from __future__ import annotations

from src.gui.job_history_panel_v2 import JobHistoryPanelV2
from src.gui.panels_v2.queue_panel_v2 import QueuePanelV2
from src.gui.preview_panel_v2 import PreviewPanelV2


def test_queue_panel_refresh_metrics_snapshot_tracks_counts_and_slow_calls() -> None:
    panel = QueuePanelV2.__new__(QueuePanelV2)
    panel._refresh_metrics = {}

    panel._record_refresh_metric("update_jobs", 5.0)
    panel._record_refresh_metric("update_jobs", 25.0)

    snapshot = panel.get_diagnostics_snapshot()
    metrics = snapshot["refresh_metrics"]["update_jobs"]

    assert snapshot["slow_threshold_ms"] == QueuePanelV2.SLOW_REFRESH_THRESHOLD_MS
    assert metrics["count"] == 2
    assert metrics["avg_ms"] == 15.0
    assert metrics["max_ms"] == 25.0
    assert metrics["last_ms"] == 25.0
    assert metrics["slow_count"] == 1


def test_job_history_panel_refresh_metrics_snapshot_tracks_counts_and_slow_calls() -> None:
    panel = JobHistoryPanelV2.__new__(JobHistoryPanelV2)
    panel._refresh_metrics = {}

    panel._record_refresh_metric("_populate_history", 4.0)
    panel._record_refresh_metric("_populate_history", 22.0)

    snapshot = panel.get_diagnostics_snapshot()
    metrics = snapshot["refresh_metrics"]["_populate_history"]

    assert snapshot["slow_threshold_ms"] == JobHistoryPanelV2.SLOW_REFRESH_THRESHOLD_MS
    assert metrics["count"] == 2
    assert metrics["avg_ms"] == 13.0
    assert metrics["max_ms"] == 22.0
    assert metrics["last_ms"] == 22.0
    assert metrics["slow_count"] == 1


def test_preview_panel_refresh_metrics_snapshot_tracks_counts_and_slow_calls() -> None:
    panel = PreviewPanelV2.__new__(PreviewPanelV2)
    panel._refresh_metrics = {}

    panel._record_refresh_metric("_render_summary", 3.0)
    panel._record_refresh_metric("_render_summary", 30.0)

    snapshot = panel.get_diagnostics_snapshot()
    metrics = snapshot["refresh_metrics"]["_render_summary"]

    assert snapshot["slow_threshold_ms"] == PreviewPanelV2.SLOW_REFRESH_THRESHOLD_MS
    assert metrics["count"] == 2
    assert metrics["avg_ms"] == 16.5
    assert metrics["max_ms"] == 30.0
    assert metrics["last_ms"] == 30.0
    assert metrics["slow_count"] == 1
