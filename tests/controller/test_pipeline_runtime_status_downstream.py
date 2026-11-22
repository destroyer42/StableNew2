"""Runtime status from queue execution must reach the AppController status the watchdog reads.

Regression: ``PipelineController._get_runtime_status_callback`` looked up ``self.app_controller``, but the
controller stores ``self._app_controller``. The downstream sink was therefore always ``None``: Comfy's execution
liveness reports were projected to the durable queue but never reached ``AppController._last_runtime_status``,
so ``SystemWatchdogV2`` raised a false ``queue_runner_stall`` (and built a diagnostics bundle) on every queued
video job longer than 90 s.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from src.controller.pipeline_controller import PipelineController


class _JobController:
    def __init__(self) -> None:
        self.projected: list[dict[str, Any]] = []

    def runtime_status_callback(self, downstream=None):
        def _project(status_data: dict[str, Any]) -> None:
            self.projected.append(dict(status_data))
            if downstream is not None:
                downstream(status_data)

        return _project


def _controller(app_controller: Any) -> tuple[PipelineController, _JobController]:
    controller = PipelineController.__new__(PipelineController)
    job_controller = _JobController()
    controller._job_controller = job_controller
    controller._app_controller = app_controller
    return controller, job_controller


def test_status_updates_reach_the_app_controller_sink() -> None:
    received: list[dict[str, Any]] = []
    app = SimpleNamespace(_get_runtime_status_callback=lambda: received.append)
    controller, job_controller = _controller(app)

    callback = controller._get_runtime_status_callback()
    callback({"job_id": "job-1", "stage_detail": "comfy executing (5s)"})

    assert job_controller.projected == [{"job_id": "job-1", "stage_detail": "comfy executing (5s)"}]
    assert received == [{"job_id": "job-1", "stage_detail": "comfy executing (5s)"}]


def test_without_an_app_controller_only_the_durable_projection_runs() -> None:
    controller, job_controller = _controller(None)

    controller._get_runtime_status_callback()({"job_id": "job-1"})

    assert job_controller.projected == [{"job_id": "job-1"}]
