"""Tests that validate the canonical controller → JobService → runner path (PR-CORE1-A3).

Validates that preview/queue/history use NJR-based DTOs only (pack-only NJR paths).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from src.controller.app_controller import AppController
from src.controller.job_service import JobService
from src.controller.pipeline_controller import PipelineController
from src.pipeline.job_models_v2 import NormalizedJobRecord, StageConfig
from src.pipeline.pipeline_runner import PipelineRunResult
from src.queue.job_model import Job, JobStatus
from src.queue.single_node_runner import SingleNodeJobRunner
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
            StageConfig(
                stage_type="txt2img", enabled=True, steps=20, cfg_scale=7.5, sampler_name="Euler a"
            )
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


def _canonical_run_result(
    job_id: str, *, success: bool = True, error: str | None = None
) -> dict[str, Any]:
    return PipelineRunResult(
        run_id=job_id,
        success=success,
        error=error,
        variants=[],
        learning_records=[],
        metadata={},
    ).to_dict()


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
    controller = PipelineController(job_service=service)
    controller._build_normalized_jobs_from_state = lambda *_: [_make_dummy_record()]

    controller._last_run_config = {"prompt_pack_id": "test-pack-core"}
    controller.start_pipeline_v2()


def test_njr_backed_job_uses_njr_execution_path(tmp_path: Path) -> None:
    """Job with _normalized_record should execute via PipelineController._run_job (PR-CORE1-B1)."""

    controller = RecordingAppController(
        main_window=None,
        threaded=False,
        tmp_history=tmp_path / "job_history.json",
    )

    # Create job with NJR
    njr = _make_dummy_record()
    job = Job(job_id="njr-test-1", priority=None)
    job._normalized_record = njr

    run_result_data = _canonical_run_result(job.job_id)
    controller.pipeline_controller._run_job = lambda j: run_result_data

    result = controller._execute_job(job)

    assert result["success"] is True
    assert result["metadata"]["execution_path"] == "njr"
    assert result["metadata"]["job_id"] == job.job_id


def test_njr_job_failure_returns_error_no_fallback_b2(tmp_path: Path) -> None:
    """PR-CORE1-B2: Job with NJR that fails execution returns error (no pipeline_config fallback)."""

    controller = RecordingAppController(
        main_window=None,
        threaded=False,
        tmp_history=tmp_path / "job_history.json",
    )

    # Create job with NJR
    njr = _make_dummy_record()
    job = Job(job_id="njr-test-fail", priority=None)
    job._normalized_record = njr

    # Mock pipeline_controller._run_job to raise exception
    def failing_run_job(j):
        raise RuntimeError("NJR execution failed")

    controller.pipeline_controller._run_job = failing_run_job

    result = controller._execute_job(job)

    # PR-CORE1-B2: Should return error status, not fall back to pipeline_config
    assert result["success"] is False
    assert "NJR execution failed" in result["error"]
    assert result["metadata"]["execution_path"] == "njr"
    assert result["metadata"]["job_id"] == job.job_id


def test_queue_jobs_have_normalized_record_b2(tmp_path: Path) -> None:
    """PR-CORE1-B2: Jobs submitted through normal queue path should have _normalized_record."""

    controller = RecordingAppController(
        main_window=None,
        threaded=False,
        tmp_history=tmp_path / "job_history.json",
    )

    # Create NJR and convert to queue job via pipeline_controller
    njr = _make_dummy_record()
    queue_job = controller.pipeline_controller._to_queue_job(njr)

    # PR-CORE1-B2: Queue jobs created from NJR must have _normalized_record attached
    assert hasattr(queue_job, "_normalized_record")
    assert queue_job._normalized_record is not None
    assert queue_job._normalized_record == njr
    assert queue_job.job_id == njr.job_id
    assert getattr(queue_job, "pipeline_config", None) is None


def test_app_controller_queue_submission_returns_quickly(tmp_path: Path) -> None:
    """Queue submissions via AppController do not block the caller thread."""

    controller = RecordingAppController(
        main_window=None,
        threaded=False,
        tmp_history=tmp_path / "job_history.json",
    )

    start_event = threading.Event()
    release_event = threading.Event()

    def blocking_run(job: Job) -> dict[str, Any]:
        start_event.set()
        release_event.wait(timeout=2.0)
        return {"job_id": job.job_id, "status": "completed"}

    runner = SingleNodeJobRunner(controller.job_service.job_queue, blocking_run, poll_interval=0.01)
    controller.job_service.runner = runner
    controller.job_service.auto_run_enabled = True  # Enable auto-run for this test

    njr = _make_dummy_record()
    queue_job = controller.pipeline_controller._to_queue_job(njr)

    start = time.monotonic()
    controller.job_service.submit_queued(queue_job)
    duration = time.monotonic() - start
    assert duration < 0.2

    assert start_event.wait(timeout=1.0)
    release_event.set()

    for _ in range(100):
        candidate = controller.job_service.job_queue.get_job(queue_job.job_id)
        if candidate and candidate.status == JobStatus.COMPLETED:
            break
        time.sleep(0.01)
    else:
        pytest.fail("Queue job did not complete after release_event")

    controller.job_service.runner.stop()
