from __future__ import annotations

from src.gui.views.pipeline_tab_frame_v2 import PipelineTabFrame


def test_pipeline_tab_callback_metrics_snapshot_tracks_counts_and_slow_calls() -> None:
    tab = PipelineTabFrame.__new__(PipelineTabFrame)
    tab._callback_metrics = {}

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
