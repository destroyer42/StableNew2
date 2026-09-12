"""Canonical queue-to-txt2img cancellation contract for PR-HARDEN-009-R1A."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.api.types import GenerateOutcome, GenerateResult
from src.controller.job_service import JobService
from src.controller.runtime_state import CancellationError, CancelToken
from src.pipeline.pipeline_runner import PipelineRunner
from src.queue.job_model import JobStatus
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from src.queue.single_node_runner import SingleNodeJobRunner
from src.utils.logger import StructuredLogger
from tests.helpers.njr_factory import make_pipeline_njr


_TINY_PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9"
    "awAAAABJRU5ErkJggg=="
)


class _BlockingTxt2ImgClient:
    """Controlled A1111 seam; production queue/executor ownership stays real."""

    def __init__(self, *, release_immediately: bool = False) -> None:
        self.post_started = threading.Event()
        self.post_released = threading.Event()
        self.interrupt_started = threading.Event()
        self._release = threading.Event()
        if release_immediately:
            self._release.set()
        self.post_count = 0
        self.interrupt_count = 0

    def generate_images(self, *, stage: str, payload: dict[str, object]) -> GenerateOutcome:
        assert stage == "txt2img"
        assert payload["prompt"]
        self.post_count += 1
        self.post_started.set()
        assert self._release.wait(timeout=2.0), "test client was not interrupted or released"
        self.post_released.set()
        return GenerateOutcome(
            result=GenerateResult(
                images=[_TINY_PNG],
                info={},
                stage="txt2img",
                timings={},
            )
        )

    def get_progress(self, *, skip_current_image: bool = True) -> SimpleNamespace:
        assert skip_current_image is True
        return SimpleNamespace(
            progress=0.25,
            eta_relative=10.0,
            current_step=5,
            total_steps=20,
            state={"job": "r1a-active"},
        )

    def get_current_model(self) -> str:
        return "sdxl"

    def get_current_vae(self) -> str:
        return "Automatic"

    def interrupt(self) -> bool:
        self.interrupt_count += 1
        self.interrupt_started.set()
        self._release.set()
        return True


def _wait_until(predicate, *, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return bool(predicate())


def _build_pipeline_runner(monkeypatch, tmp_path: Path, client: _BlockingTxt2ImgClient) -> PipelineRunner:
    runner = PipelineRunner(
        api_client=client,
        structured_logger=StructuredLogger(output_dir=tmp_path / "logs"),
        runs_base_dir=str(tmp_path / "runs"),
    )
    executor = runner._pipeline
    monkeypatch.setattr(executor, "_ensure_webui_true_ready", lambda: None)
    monkeypatch.setattr(executor, "_check_webui_health_before_stage", lambda _stage: None)
    monkeypatch.setattr(executor, "_ensure_model_and_vae", lambda *_args: None)
    monkeypatch.setattr(executor, "_apply_webui_defaults_once", lambda: None)
    monkeypatch.setattr(executor, "_assess_stage_pressure", lambda **_kwargs: {})
    monkeypatch.setattr(executor, "_mitigate_stage_pressure", lambda _assessment: None)
    monkeypatch.setattr(executor, "_maybe_apply_workload_launch_policy", lambda **_kwargs: None)
    monkeypatch.setattr(
        executor,
        "_ensure_runtime_admissible",
        lambda **_kwargs: {"status": "healthy", "reasons": []},
    )
    return runner


def _build_record(tmp_path: Path, *, job_id: str):
    return make_pipeline_njr(
        job_id=job_id,
        positive_prompt="cancel during canonical txt2img",
        path_output_dir=str(tmp_path / "runs"),
    )


def _production_thread_names() -> set[str]:
    return {
        thread.name
        for thread in threading.enumerate()
        if thread.name.startswith(("QueueWorker", "progress_poll"))
    }


def test_canonical_txt2img_cancel_interrupts_once_and_persists_cancelled(monkeypatch, tmp_path: Path) -> None:
    client = _BlockingTxt2ImgClient()
    pipeline_runner = _build_pipeline_runner(monkeypatch, tmp_path, client)
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    queue = JobQueue(repository=repository)

    def run_job(job):
        return pipeline_runner.run_njr(
            job._normalized_record,
            cancel_token=job._cancel_token,
        ).to_dict()

    runner = SingleNodeJobRunner(queue, run_job, poll_interval=0.01)
    service = JobService(queue, runner)
    service.auto_run_enabled = True
    record = _build_record(tmp_path, job_id="r1a-cancel")

    try:
        service.submit_njrs([record])
        assert client.post_started.wait(timeout=1.0)
        assert queue.get_job(record.job_id).status is JobStatus.RUNNING
        token = runner._current_cancel_token
        assert token is not None
        assert "QueueWorker" in _production_thread_names()

        cancellation_started = time.monotonic()
        service.cancel_current()

        assert token.is_cancelled()
        assert client.interrupt_started.wait(timeout=1.0)
        assert client.post_released.wait(timeout=1.0)
        assert _wait_until(lambda: runner.current_job is None)
        cancellation_elapsed = time.monotonic() - cancellation_started
        persisted = repository.get_job_model(record.job_id)

        assert cancellation_elapsed < 2.0
        assert client.post_count == 1
        assert client.interrupt_count == 1
        assert persisted is not None
        assert persisted.status is JobStatus.CANCELLED
        assert persisted.result is None
        assert repository.get_artifact_references(record.job_id) == []
        assert not list((tmp_path / "runs").rglob("*.png"))
        assert _wait_until(lambda: not any(name.startswith("progress_poll") for name in _production_thread_names()))
    finally:
        service.stop()

    assert not any(name.startswith("QueueWorker") for name in _production_thread_names())


def test_canonical_txt2img_completes_once_when_not_cancelled(monkeypatch, tmp_path: Path) -> None:
    client = _BlockingTxt2ImgClient(release_immediately=True)
    pipeline_runner = _build_pipeline_runner(monkeypatch, tmp_path, client)
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    queue = JobQueue(repository=repository)

    def run_job(job):
        return pipeline_runner.run_njr(
            job._normalized_record,
            cancel_token=job._cancel_token,
        ).to_dict()

    runner = SingleNodeJobRunner(queue, run_job, poll_interval=0.01)
    service = JobService(queue, runner)
    service.auto_run_enabled = True
    record = _build_record(tmp_path, job_id="r1a-complete")

    try:
        service.submit_njrs([record])
        assert _wait_until(
            lambda: (job := repository.get_job_model(record.job_id)) is not None
            and job.status is JobStatus.COMPLETED
        )
        assert client.post_count == 1
        assert client.interrupt_count == 0
    finally:
        service.stop()


def test_cancelled_token_prevents_txt2img_post_before_dispatch(monkeypatch, tmp_path: Path) -> None:
    client = _BlockingTxt2ImgClient()
    pipeline_runner = _build_pipeline_runner(monkeypatch, tmp_path, client)
    token = CancelToken()
    token.cancel()

    with pytest.raises(CancellationError, match="Cancelled during txt2img stage start"):
        pipeline_runner.run_njr(_build_record(tmp_path, job_id="r1a-pre-cancel"), token)

    assert client.post_count == 0
