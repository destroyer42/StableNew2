"""Tests that validate the canonical controller → JobService → runner path (PR-CORE1-A3).

Validates that preview/queue/history use NJR-based DTOs only (pack-only NJR paths).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from src.controller.app_controller import AppController
from src.controller.pipeline_controller import PipelineController
from src.controller.webui_connection_controller import (
    WebUIConnectionController,
    WebUIConnectionState,
)
from src.pipeline.job_models_v2 import NormalizedJobRecord, SourceKind, StageConfig
from src.pipeline.pipeline_runner import PipelineRunResult
from src.queue.job_model import Job
from src.utils.logger import StructuredLogger, close_all_structured_loggers
from tests.helpers.njr_factory import make_pipeline_njr


@pytest.fixture(autouse=True)
def _close_structured_loggers_after_test():
    yield
    close_all_structured_loggers()


class RecordingAppController(AppController):
    """AppController variant that records the runner factory run_callable."""

    def __init__(self, *args: object, tmp_history: Path | None = None, **kwargs: object) -> None:
        self._custom_history = tmp_history
        self.recorded_callables: list[Callable[[Job], dict]] = []
        if tmp_history is not None and "structured_logger" not in kwargs:
            kwargs["structured_logger"] = StructuredLogger(
                output_dir=str(tmp_history.parent / "structured_logs")
            )
        super().__init__(*args, **kwargs)


def _make_dummy_record() -> NormalizedJobRecord:
    return make_pipeline_njr(
        job_id="test-dummy",
        config={"prompt": "stub prompt", "model": "sdxl"},
        seed=11111,
        prompt_pack_id="test-pack-core",
        prompt_pack_name="test pack",
        positive_prompt="stub prompt",
        negative_prompt="neg: bad",
        positive_embeddings=["stub"],
        source_kind=SourceKind.PROMPT_PACK.value,
        stage_chain=[
            StageConfig(
                stage_type="txt2img", enabled=True, steps=20, cfg_scale=7.5, sampler_name="Euler a"
            )
        ],
        base_model="sdxl",
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


def test_app_controller_adopts_pipeline_controller_queue_stack(tmp_path: Path) -> None:
    """AppController should use the PipelineController-owned queue/job-service stack."""

    controller = RecordingAppController(
        main_window=None,
        threaded=False,
        tmp_history=tmp_path / "job_history.json",
    )

    job_service = controller.pipeline_controller.get_job_service()
    job_exec = controller.pipeline_controller.get_job_execution_controller()

    assert controller.job_service is job_service
    assert job_service is not None
    assert job_service.queue is job_exec.get_queue()


def test_pipeline_controller_routes_jobs_through_job_service(
    job_service_with_stub_runner_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PipelineController admits the preview NJR through the canonical JobService boundary."""
    service, queue, _ = job_service_with_stub_runner_factory
    submit = Mock(wraps=service.submit_njrs)
    monkeypatch.setattr(service, "submit_njrs", submit)
    connection = Mock(spec=WebUIConnectionController)
    connection.ensure_connected.return_value = WebUIConnectionState.READY
    controller = PipelineController(job_service=service, webui_connection_controller=connection)
    record = _make_dummy_record()
    monkeypatch.setattr(controller, "get_preview_jobs", lambda: [record])

    assert controller.start_pipeline_v2()

    submit.assert_called_once()
    assert list(submit.call_args.args[0]) == [record]
    stored = queue.repository.get_job_model(record.job_id)
    assert stored is not None
    assert stored._normalized_record == record


def test_queue_jobs_have_normalized_record_b2(tmp_path: Path) -> None:
    """PR-CORE1-B2: Jobs submitted through normal queue path should have _normalized_record."""

    controller = RecordingAppController(
        main_window=None,
        threaded=False,
        tmp_history=tmp_path / "job_history.json",
    )
    controller.job_service.auto_run_enabled = False

    try:
        # Submit the compiled NJR through the application boundary.
        njr = _make_dummy_record()
        controller.job_service.submit_njrs([njr])
        queue_job = controller.job_service.job_queue.get_job(njr.job_id)
        assert queue_job is not None

        # PR-CORE1-B2: Queue jobs created from NJR must have _normalized_record attached
        assert hasattr(queue_job, "_normalized_record")
        assert queue_job._normalized_record is not None
        assert queue_job._normalized_record == njr
        assert queue_job.job_id == njr.job_id
        assert getattr(queue_job, "pipeline_config", None) is None
    finally:
        controller.job_service.stop()


def test_app_controller_queue_submission_returns_quickly(tmp_path: Path) -> None:
    """Queue submissions via AppController do not block the caller thread."""

    controller = RecordingAppController(
        main_window=None,
        threaded=False,
        tmp_history=tmp_path / "job_history.json",
    )
    controller.job_service.job_queue.clear()

    start_event = threading.Event()
    release_event = threading.Event()
    njr = _make_dummy_record()
    queue_job_id = njr.job_id

    class ControlledAsyncRunner:
        def __init__(self, job_queue, target_job_id: str) -> None:
            self.job_queue = job_queue
            self._target_job_id = target_job_id
            self._worker: threading.Thread | None = None
            self._stop_event = threading.Event()
            self._current_job: Job | None = None

        def start(self) -> None:
            if self.is_running():
                return
            self._stop_event.clear()
            start_event.set()

            def _worker() -> None:
                job = self.job_queue.get_job(self._target_job_id)
                if job is None:
                    return
                self._current_job = job
                self.job_queue.mark_running(job.job_id)
                release_event.wait(timeout=2.0)
                self.job_queue.mark_completed(
                    job.job_id,
                    result={"job_id": job.job_id, "status": "completed"},
                )
                self._current_job = None

            self._worker = threading.Thread(
                target=_worker, name="ControlledAsyncRunner", daemon=True
            )
            self._worker.start()

        def stop(self) -> None:
            self._stop_event.set()
            worker = self._worker
            if worker is not None:
                worker.join(timeout=1.0)
            self._worker = None
            self._current_job = None

        def is_running(self) -> bool:
            return self._worker is not None and self._worker.is_alive()

        def cancel_current(self, *, return_to_queue: bool = False) -> None:
            self._stop_event.set()

        @property
        def current_job(self) -> Job | None:
            return self._current_job

    runner = ControlledAsyncRunner(controller.job_service.job_queue, queue_job_id)
    controller.pipeline_controller.replace_queue_runner(runner)
    assert controller.job_service.runner is runner
    assert controller.pipeline_controller.get_job_execution_controller().get_runner() is runner
    controller.job_service.auto_run_enabled = True  # Enable auto-run for this test

    start = time.monotonic()
    controller.job_service.submit_njrs([njr])
    duration = time.monotonic() - start
    assert duration < 0.2

    assert start_event.wait(timeout=1.0)
    release_event.set()
    controller.job_service.runner.stop()
    assert not controller.job_service.runner.is_running()


def test_app_controller_wires_current_global_prompt_policy_into_pipeline_controller(
    tmp_path: Path,
) -> None:
    """Preview compilation must see the app's current global prompt intent."""

    controller = RecordingAppController(
        main_window=None, threaded=False, tmp_history=tmp_path / "job_history.json"
    )
    getter = controller.pipeline_controller.get_current_global_prompt_policy  # type: ignore[attr-defined]

    assert getter() == controller.get_current_global_prompt_policy()
