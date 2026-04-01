from __future__ import annotations

from types import SimpleNamespace

from src.contracts import QueueProjection, RuntimeProjection
from src.gui.app_state_projection_sink import AppStateProjectionSink
from src.gui.app_state_v2 import AppStateV2


def test_app_state_projection_sink_applies_latest_revision_only() -> None:
    app_state = AppStateV2()
    sink = AppStateProjectionSink(app_state)

    newer_job = SimpleNamespace(job_id="job-2")
    older_job = SimpleNamespace(job_id="job-1")
    sink.apply_queue_projection(
        QueueProjection(revision=2, queue_items=("job-2",), queue_jobs=(newer_job,))
    )
    sink.apply_queue_projection(
        QueueProjection(revision=1, queue_items=("job-1",), queue_jobs=(older_job,))
    )

    assert app_state.queue_items == ["job-2"]
    assert list(app_state.queue_jobs) == [newer_job]
    metrics = sink.get_metrics_snapshot()
    assert metrics["surface_revisions"]["queue"] == 2
    assert metrics["skipped_counts"]["queue"] == 1


def test_app_state_projection_sink_updates_runtime_surface_fields() -> None:
    app_state = AppStateV2()
    sink = AppStateProjectionSink(app_state)
    running = SimpleNamespace(job_id="job-7")
    runtime = SimpleNamespace(job_id="job-7", current_stage="txt2img")

    sink.apply_runtime_projection(
        RuntimeProjection(
            revision=1,
            running_job=running,
            runtime_status=runtime,
            queue_status="running",
            webui_state="connected",
            last_error=None,
        )
    )

    assert app_state.running_job is running
    assert app_state.runtime_status is runtime
    assert app_state.queue_status == "running"
    assert app_state.webui_state == "connected"

