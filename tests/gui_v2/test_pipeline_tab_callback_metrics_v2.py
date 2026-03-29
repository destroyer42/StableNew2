from __future__ import annotations

from src.gui.views.pipeline_tab_frame_v2 import PipelineTabFrame


class _FakeDiagnosticsPanel:
    def __init__(self, name: str) -> None:
        self._name = name

    def get_diagnostics_snapshot(self) -> dict[str, object]:
        return {"panel": self._name}


def test_pipeline_tab_callback_metrics_snapshot_tracks_counts_and_slow_calls() -> None:
    tab = PipelineTabFrame.__new__(PipelineTabFrame)
    tab._callback_metrics = {}
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
    assert snapshot["queue_panel"] == {"panel": "queue"}
    assert snapshot["history_panel"] == {"panel": "history"}
    assert snapshot["preview_panel"] == {"panel": "preview"}
