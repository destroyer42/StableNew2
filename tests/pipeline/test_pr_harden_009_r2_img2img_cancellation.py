"""Canonical queue-to-img2img cancellation contract for PR-HARDEN-009-R2."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.api.types import GenerateOutcome, GenerateResult
from src.controller.job_service import JobService
from src.controller.runtime_state import CancellationError, CancelToken
from src.pipeline.executor import Pipeline
from src.pipeline.pipeline_runner import PipelineRunner
from src.queue.job_model import JobStatus
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from src.queue.single_node_runner import SingleNodeJobRunner
from src.utils.logger import StructuredLogger
from tests.helpers.njr_factory import make_pipeline_njr, make_stage_config

_TINY_PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgWJ9awAAAABJRU5ErkJggg=="
)


class _BlockingImg2ImgClient:
    """Controlled A1111 seam; production executor/queue ownership stays real."""

    def __init__(self, *, release_immediately: bool = False) -> None:
        self.post_started = threading.Event()
        self.post_returned = threading.Event()
        self.interrupt_started = threading.Event()
        self._release = threading.Event()
        if release_immediately:
            self._release.set()
        self.post_count = 0
        self.interrupt_count = 0

    def generate_images(self, *, stage: str, payload: dict[str, object]) -> GenerateOutcome:
        assert stage == "img2img"
        assert payload["prompt"]
        self.post_count += 1
        self.post_started.set()
        assert self._release.wait(timeout=2.0), "test client was not interrupted or released"
        self.post_returned.set()
        return GenerateOutcome(
            result=GenerateResult(
                images=[_TINY_PNG],
                info={},
                stage="img2img",
                timings={},
            )
        )

    def get_progress(self, *, skip_current_image: bool = True) -> SimpleNamespace:
        assert skip_current_image is True
        return SimpleNamespace(
            progress=0.5,
            eta_relative=10.0,
            current_step=10,
            total_steps=20,
            current_image=None,
            state={"job": "r2-active-img2img"},
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


def _fake_save_image(_data: str, path: Path, metadata_builder=None) -> Path:
    del metadata_builder
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"img2img-artifact")
    return path


def _build_pipeline(monkeypatch, tmp_path: Path, client: _BlockingImg2ImgClient) -> Pipeline:
    pipeline = Pipeline(
        client=client,
        structured_logger=StructuredLogger(output_dir=tmp_path / "logs"),
    )
    monkeypatch.setattr(pipeline, "_ensure_webui_true_ready", lambda: None)
    monkeypatch.setattr(pipeline, "_check_webui_health_before_stage", lambda _stage: None)
    monkeypatch.setattr(pipeline, "_ensure_model_and_vae", lambda *_args: None)
    monkeypatch.setattr(pipeline, "_ensure_hypernetwork", lambda *_args: None)
    monkeypatch.setattr(pipeline, "_load_image_base64", lambda _path: "input-base64")
    monkeypatch.setattr("src.pipeline.executor.save_image_from_base64", _fake_save_image)
    return pipeline


def test_active_img2img_cancel_interrupts_once_and_promotes_no_artifact(
    monkeypatch, tmp_path: Path
) -> None:
    client = _BlockingImg2ImgClient()
    pipeline = _build_pipeline(monkeypatch, tmp_path, client)
    input_path = tmp_path / "input.png"
    output_dir = tmp_path / "outputs"
    input_path.write_bytes(b"input")
    token = CancelToken()
    errors: list[BaseException] = []

    def execute() -> None:
        try:
            pipeline.run_img2img_stage(
                input_image_path=input_path,
                prompt="cancel during img2img",
                config={"steps": 20, "model": "sdxl"},
                output_dir=output_dir,
                image_name="img2img-cancelled",
                cancel_token=token,
            )
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    worker = threading.Thread(target=execute, name="r2-img2img-test")
    worker.start()
    assert client.post_started.wait(timeout=1.0)
    token.cancel()
    assert client.interrupt_started.wait(timeout=1.0)
    assert client.post_returned.wait(timeout=1.0)
    worker.join(timeout=2.0)

    assert not worker.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], CancellationError)
    assert client.post_count == 1
    assert client.interrupt_count == 1
    assert not list(output_dir.rglob("*.png"))


def test_img2img_cancel_before_dispatch_sends_no_post_or_interrupt(
    monkeypatch, tmp_path: Path
) -> None:
    client = _BlockingImg2ImgClient()
    pipeline = _build_pipeline(monkeypatch, tmp_path, client)
    input_path = tmp_path / "input.png"
    input_path.write_bytes(b"input")
    token = CancelToken()
    token.cancel()

    with pytest.raises(CancellationError, match="Cancelled during img2img stage start"):
        pipeline.run_img2img_stage(
            input_image_path=input_path,
            prompt="already cancelled",
            config={"steps": 20},
            output_dir=tmp_path / "outputs",
            image_name="img2img-pre-cancelled",
            cancel_token=token,
        )

    assert client.post_count == 0
    assert client.interrupt_count == 0


def test_img2img_success_still_posts_once_without_interrupt(monkeypatch, tmp_path: Path) -> None:
    client = _BlockingImg2ImgClient(release_immediately=True)
    pipeline = _build_pipeline(monkeypatch, tmp_path, client)
    input_path = tmp_path / "input.png"
    output_dir = tmp_path / "outputs"
    input_path.write_bytes(b"input")

    result = pipeline.run_img2img_stage(
        input_image_path=input_path,
        prompt="normal img2img",
        config={"steps": 20},
        output_dir=output_dir,
        image_name="img2img-success",
    )

    assert result is not None
    assert client.post_count == 1
    assert client.interrupt_count == 0
    assert (output_dir / "img2img-success.png").exists()


def test_img2img_cancel_after_response_wins_before_artifact_promotion(
    monkeypatch, tmp_path: Path
) -> None:
    client = _BlockingImg2ImgClient()
    pipeline = _build_pipeline(monkeypatch, tmp_path, client)
    input_path = tmp_path / "input.png"
    output_dir = tmp_path / "outputs"
    input_path.write_bytes(b"input")
    token = CancelToken()

    def return_then_cancel(_stage, _payload, **kwargs):
        assert kwargs["cancel_token"] is token
        token.cancel()
        return {"images": [_TINY_PNG], "info": {}}

    monkeypatch.setattr(pipeline, "_generate_images_with_progress", return_then_cancel)

    with pytest.raises(CancellationError, match="Cancelled during img2img post-call"):
        pipeline.run_img2img_stage(
            input_image_path=input_path,
            prompt="late response must not win",
            config={"steps": 20},
            output_dir=output_dir,
            image_name="img2img-late-success",
            cancel_token=token,
        )

    assert client.post_count == 0
    assert client.interrupt_count == 0
    assert not list(output_dir.rglob("*.png"))


def test_queue_img2img_cancel_persists_cancelled_and_skips_later_stage(
    monkeypatch, tmp_path: Path
) -> None:
    client = _BlockingImg2ImgClient()
    pipeline_runner = PipelineRunner(
        api_client=client,
        structured_logger=StructuredLogger(output_dir=tmp_path / "logs"),
        runs_base_dir=str(tmp_path / "runs"),
    )
    executor = pipeline_runner._pipeline
    monkeypatch.setattr(executor, "_ensure_webui_true_ready", lambda: None)
    monkeypatch.setattr(executor, "_check_webui_health_before_stage", lambda _stage: None)
    monkeypatch.setattr(executor, "_ensure_model_and_vae", lambda *_args: None)
    monkeypatch.setattr(executor, "_ensure_hypernetwork", lambda *_args: None)
    monkeypatch.setattr(executor, "_load_image_base64", lambda _path: "input-base64")
    monkeypatch.setattr("src.pipeline.executor.save_image_from_base64", _fake_save_image)
    later_stage_calls: list[str] = []
    monkeypatch.setattr(
        executor,
        "run_adetailer_stage",
        lambda *args, **kwargs: later_stage_calls.append("adetailer"),
    )

    input_path = tmp_path / "input.png"
    input_path.write_bytes(b"input")
    record = make_pipeline_njr(
        job_id="r2-img2img-cancel",
        positive_prompt="cancel active img2img",
        input_image_paths=(str(input_path),),
        start_stage="img2img",
        path_output_dir=str(tmp_path / "runs"),
        stage_chain=(
            make_stage_config("img2img"),
            make_stage_config("adetailer", extra={"adetailer_enabled": True}),
        ),
    )
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

    try:
        service.submit_njrs([record])
        assert client.post_started.wait(timeout=1.0)
        service.cancel_current()
        assert client.interrupt_started.wait(timeout=1.0)
        assert _wait_until(lambda: runner.current_job is None)

        persisted = repository.get_job_model(record.job_id)
        assert persisted is not None
        assert persisted.status is JobStatus.CANCELLED
        assert persisted.result is None
        assert repository.get_artifact_references(record.job_id) == []
        assert client.post_count == 1
        assert client.interrupt_count == 1
        assert later_stage_calls == []
        assert not list((tmp_path / "runs").rglob("*.png"))
    finally:
        service.stop()
