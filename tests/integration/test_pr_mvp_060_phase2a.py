from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.controller.job_execution_controller import JobExecutionController
from src.controller.job_service import JobService
from src.controller.pipeline_controller import PipelineController
from src.controller.runtime_state import CancellationError
from src.gui.panels_v2.running_job_panel_v2 import RunningJobPanelV2
from src.pipeline.executor import Pipeline
from src.queue.job_model import JobStatus
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from src.queue.single_node_runner import SingleNodeJobRunner
from src.utils import StructuredLogger
from tests.helpers.njr_factory import make_queue_job


def _wait_until(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not reached before timeout")


class _AppState:
    def __init__(self) -> None:
        self.statuses = []

    def set_runtime_status(self, status) -> None:
        self.statuses.append(status)


def test_txt2img_progress_is_monotonic_durable_and_cleared_at_completion(tmp_path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    queue = JobQueue(repository=repository)
    controller = JobExecutionController(
        queue=queue,
        replay_runner=SimpleNamespace(run_njr=lambda *_args, **_kwargs: None),
        restore_state=False,
    )
    app_state = _AppState()
    controller.set_app_state(app_state)
    job = make_queue_job("progress-job")
    queue.submit(job)
    queue.mark_running(job.job_id)

    for step, progress in enumerate((0.25, 0.50, 0.40, 0.75, 1.20), start=1):
        controller._handle_runtime_status_update(
            {
                "job_id": job.job_id,
                "current_stage": "txt2img",
                "progress": progress,
                "eta_seconds": float(5 - min(step, 4)),
                "current_step": min(step, 4),
                "total_steps": 4,
            }
        )

    persisted = repository.get_job_model(job.job_id)
    assert persisted is not None
    assert [status.progress for status in app_state.statuses] == [0.25, 0.50, 0.50, 0.75, 1.0]
    assert persisted.progress == 1.0
    assert persisted.eta_seconds == 1.0
    assert app_state.statuses[-1].current_stage == "txt2img"
    assert (app_state.statuses[-1].current_step, app_state.statuses[-1].total_steps) == (4, 4)

    queue.mark_completed(job.job_id, {"success": True})
    terminal = repository.get_job_model(job.job_id)
    assert terminal is not None
    assert terminal.status == JobStatus.COMPLETED
    assert terminal.progress == 0.0
    assert terminal.eta_seconds is None


def test_injected_production_runner_is_bound_to_durable_progress_projection(tmp_path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    queue = JobQueue(repository=repository)
    service = JobService(queue, run_callable=lambda _job: {"success": True})
    runtime_runner = Mock()
    controller = PipelineController(job_service=service, pipeline_runner=runtime_runner)
    job = make_queue_job("bound-progress-job")
    queue.submit(job)
    queue.mark_running(job.job_id)

    assert controller._create_runtime_pipeline_runner() is runtime_runner
    callback = runtime_runner.set_status_callback.call_args.args[0]
    callback({"job_id": job.job_id, "current_stage": "txt2img", "progress": 0.5})

    persisted = repository.get_job_model(job.job_id)
    assert persisted is not None
    assert persisted.progress == 0.5


def test_queued_cancel_is_durable_and_never_dispatches_cancelled_job(tmp_path) -> None:
    queue = JobQueue(repository=JobRepository(tmp_path / "jobs.sqlite3"))
    calls: list[str] = []
    runner = SingleNodeJobRunner(
        queue, lambda job: calls.append(job.job_id) or {"success": True}, poll_interval=0.01
    )
    service = JobService(queue, runner=runner)
    cancelled = make_queue_job("cancel-before-run")
    following = make_queue_job("following-job")
    original_following_snapshot = following.snapshot
    service.enqueue(cancelled)
    service.enqueue(following)

    service.cancel_job(cancelled.job_id, reason="user_cancelled")
    runner.start()
    _wait_until(lambda: queue.repository.get_job_model(following.job_id).status == JobStatus.COMPLETED)
    runner.stop()

    stored = queue.repository.get_job_model(cancelled.job_id)
    assert stored is not None
    assert stored.status == JobStatus.CANCELLED
    assert stored.result is None
    assert calls == [following.job_id]
    assert following.snapshot == original_following_snapshot


class _BlockingA1111:
    def __init__(self) -> None:
        self.interrupt_calls = 0
        self.interrupted = threading.Event()

    def get_progress(self, **_kwargs):
        return SimpleNamespace(
            progress=0.5,
            eta_relative=1.0,
            current_step=2,
            total_steps=4,
            seed=123,
        )

    def interrupt(self) -> None:
        self.interrupt_calls += 1
        self.interrupted.set()


def test_running_cancel_interrupts_once_late_success_loses_and_queue_continues(tmp_path) -> None:
    queue = JobQueue(repository=JobRepository(tmp_path / "jobs.sqlite3"))
    client = _BlockingA1111()
    pipeline = Pipeline(client, StructuredLogger(output_dir=tmp_path / "logs"))
    generation_started = threading.Event()
    calls: list[str] = []

    def _generate(_stage, _payload):
        generation_started.set()
        assert client.interrupted.wait(2.0)
        return {"images": ["late-image"], "info": {}}

    pipeline._generate_images = _generate

    def _execute(job):
        calls.append(job.job_id)
        if job.job_id == "running-a":
            response = pipeline._generate_images_with_progress(
                "txt2img", {}, poll_interval=0.01, cancel_token=job._cancel_token
            )
            return {"success": True, "variants": [{"path": response["images"][0]}]}
        return {"success": True, "variants": [{"path": "b.png"}]}

    runner = SingleNodeJobRunner(queue, _execute, poll_interval=0.01)
    service = JobService(queue, runner=runner)
    first = make_queue_job("running-a")
    second = make_queue_job("queued-b")
    service.enqueue(first)
    service.enqueue(second)
    runner.start()
    assert generation_started.wait(2.0)

    service.cancel_current()
    _wait_until(lambda: queue.repository.get_job_model(first.job_id).status == JobStatus.CANCELLED)
    _wait_until(lambda: queue.repository.get_job_model(second.job_id).status == JobStatus.COMPLETED)
    runner.stop()

    cancelled = queue.repository.get_job_model(first.job_id)
    assert cancelled is not None
    assert cancelled.status == JobStatus.CANCELLED
    assert cancelled.result is None
    assert client.interrupt_calls == 1
    assert calls == [first.job_id, second.job_id]


def test_cancel_presentation_state_and_canonical_callback() -> None:
    assert RunningJobPanelV2._can_cancel_job(None) is False
    assert RunningJobPanelV2._can_cancel_job(SimpleNamespace(status="COMPLETED")) is False
    assert RunningJobPanelV2._can_cancel_job(SimpleNamespace(status="RUNNING")) is True

    controller = Mock()
    panel = object.__new__(RunningJobPanelV2)
    panel.controller = controller
    panel._on_cancel()
    controller.on_cancel_current_job.assert_called_once_with()


def test_unrelated_backend_failure_remains_failure(tmp_path) -> None:
    queue = JobQueue(repository=JobRepository(tmp_path / "jobs.sqlite3"))
    runner = SingleNodeJobRunner(queue, lambda _job: (_ for _ in ()).throw(RuntimeError("boom")))
    job = make_queue_job("failed-job")
    queue.submit(job)

    with pytest.raises(RuntimeError, match="boom"):
        runner.run_once(job)

    assert queue.repository.get_job_model(job.job_id).status == JobStatus.FAILED
