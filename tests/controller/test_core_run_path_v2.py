"""Tests that validate the canonical controller → JobService → runner path."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest

from src.controller.app_controller import AppController
from src.controller.job_service import JobService
from src.controller.pipeline_controller import PipelineController
from src.gui.state import StateManager
from src.queue.job_model import Job
from src.queue.stub_runner import StubRunner


class RecordingAppController(AppController):
    """AppController variant that records the runner factory run_callable."""

    def __init__(self, *args: object, tmp_history: Path | None = None, **kwargs: object) -> None:
        self._custom_history = tmp_history
        self.recorded_callables: list[Callable[[Job], dict]] = []
        super().__init__(*args, **kwargs)

    def _single_node_runner_factory(
        self,
        job_queue,
        run_callable: Callable[[Job], dict] | None,
    ) -> StubRunner:
        self.recorded_callables.append(run_callable)
        return StubRunner(job_queue, run_callable=run_callable)

    def _build_job_service(self) -> JobService:
        if self._custom_history:
            self._job_history_path = self._custom_history
        return super()._build_job_service()


class DummyNormalizedJobRecord:
    def __init__(self) -> None:
        self.job_id = "test-dummy"
        self.config = None
        self.randomizer_summary = None
        self.variant_index = 0
        self.variant_total = 0

    def to_queue_snapshot(self) -> dict[str, object]:
        return {}


def test_app_controller_builds_job_service_with_execute_callable(tmp_path: Path) -> None:
    """JobService gets constructed through the runner factory using _execute_job."""

    controller = RecordingAppController(
        main_window=None,
        threaded=False,
        tmp_history=tmp_path / "job_history.json",
    )

    assert controller.recorded_callables, "runner factory was not invoked"
    recorded = controller.recorded_callables[0]
    assert getattr(recorded, "__self__", None) is controller
    assert getattr(recorded, "__func__", recorded) is controller._execute_job.__func__


def test_pipeline_controller_routes_jobs_through_job_service(
    job_service_with_stub_runner_factory,
) -> None:
    """PipelineController submits normalized jobs via JobService only."""

    service, _, _ = job_service_with_stub_runner_factory
    submitted: list[str] = []
    original_submit = JobService.submit_job_with_run_mode.__get__(service, JobService)

    def tracking_submit(job: Job) -> None:
        submitted.append(job.job_id)
        original_submit(job)

    service.submit_job_with_run_mode = tracking_submit  # type: ignore[assignment]
    controller = PipelineController(state_manager=StateManager(), job_service=service)
    controller._build_normalized_jobs_from_state = lambda *_: [DummyNormalizedJobRecord()]

    result = controller.start_pipeline_v2()

    assert result is True
    assert submitted, "No jobs were submitted to JobService"
