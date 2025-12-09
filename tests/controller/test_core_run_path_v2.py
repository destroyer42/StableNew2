"""Tests that validate the canonical controller → JobService → runner path."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest

from src.controller.app_controller import AppController
from src.controller.job_service import JobService
from src.controller.pipeline_controller import PipelineController
from src.gui.state import StateManager
from src.pipeline.job_models_v2 import JobStatusV2, NormalizedJobRecord, StageConfig
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


def _make_dummy_record() -> NormalizedJobRecord:
    return NormalizedJobRecord(
        job_id="test-dummy",
        config={"prompt": "stub prompt", "model": "sdxl"},
        path_output_dir="output",
        filename_template="{seed}",
        seed=11111,
        variant_index=0,
        variant_total=1,
        batch_index=0,
        batch_total=1,
        created_ts=1000.0,
        prompt_pack_id="test-pack-core",
        prompt_pack_name="test pack",
        positive_prompt="stub prompt",
        negative_prompt="neg: bad",
        positive_embeddings=["stub"],
        stage_chain=[
            StageConfig(stage_type="txt2img", enabled=True, steps=20, cfg_scale=7.5, sampler_name="Euler a")
        ],
        steps=20,
        cfg_scale=7.5,
        width=512,
        height=512,
        sampler_name="Euler a",
        scheduler="ddim",
        base_model="sdxl",
        queue_source="ADD_TO_QUEUE",
        run_mode="QUEUE",
    )

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
    controller._build_normalized_jobs_from_state = lambda *_: [_make_dummy_record()]

    controller._last_run_config = {"prompt_pack_id": "test-pack-core"}
    result = controller.start_pipeline_v2()

    assert result is True
    assert submitted, "No jobs were submitted to JobService"
