from __future__ import annotations

import threading
from unittest.mock import Mock

import pytest

from src.api.client import ProgressInfo
from src.api.types import GenerateError, GenerateErrorCode, GenerateOutcome, GenerateResult
from src.pipeline.executor import EXTERNAL_WEBUI_STALL_ACTION_REQUIRED, Pipeline, PipelineStageError
from src.queue.job_model import JobStatus
from src.queue.job_queue import JobQueue
from src.queue.single_node_runner import SingleNodeJobRunner
from src.utils import StructuredLogger
from tests.helpers.njr_factory import make_queue_job


class _BlockingGenerationClient:
    def __init__(self, *, release_on_interrupt: bool = False) -> None:
        self.release_on_interrupt = release_on_interrupt
        self.release = threading.Event()
        self.post_count = 0
        self.interrupt_count = 0

    def generate_images(self, *, stage: str, payload: dict[str, object]) -> GenerateOutcome:
        assert stage == "txt2img"
        assert payload["prompt"]
        self.post_count += 1
        assert self.release.wait(timeout=2.0), "generation was not released by the test boundary"
        if self.release_on_interrupt:
            return GenerateOutcome(
                result=GenerateResult(images=["image"], info={}, stage=stage, timings={})
            )
        return GenerateOutcome(
            error=GenerateError(
                code=GenerateErrorCode.OUTCOME_UNKNOWN,
                message="connection broke after dispatch",
                stage=stage,
                details={
                    "diagnostics": {
                        "request_summary": {
                            "endpoint": "/sdapi/v1/txt2img",
                            "method": "POST",
                            "stage": stage,
                            "status": None,
                        },
                        "webui_unavailable": False,
                        "crash_suspected": False,
                    }
                },
            )
        )

    def get_progress(self, *, skip_current_image: bool = True) -> ProgressInfo:
        assert skip_current_image is True
        return ProgressInfo(
            progress=0.5,
            eta_relative=None,
            current_step=10,
            total_steps=20,
            current_image=None,
            state={"job_timestamp": "r1d-generation"},
        )

    def interrupt(self) -> bool:
        self.interrupt_count += 1
        if self.release_on_interrupt:
            self.release.set()
        return True


class _ProcessManager:
    def __init__(self, client: _BlockingGenerationClient, *, managed: bool) -> None:
        self.process = object() if managed else None
        self.owns_process = managed
        self._managed = managed
        self._client = client
        self.restart_count = 0
        self.start_count = 0
        self.stop_count = 0

    def is_running(self) -> bool:
        return self._managed

    def restart_webui(self, **kwargs) -> bool:
        self.restart_count += 1
        assert kwargs == {"wait_ready": True, "max_attempts": 1}
        self._client.release.set()
        return True

    def start(self) -> None:
        self.start_count += 1

    def stop_webui(self) -> None:
        self.stop_count += 1

    def get_recent_output_tail(self):
        return None


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now


class _ClockStopEvent:
    def __init__(self, clock: _FakeClock, *, stop_after: float) -> None:
        self._clock = clock
        self._stop_after = stop_after
        self._set = False

    def is_set(self) -> bool:
        return self._set

    def wait(self, duration: float) -> bool:
        self._clock.now += duration
        self._set = self._clock.now > self._stop_after
        return self._set


def _pipeline(client, *, status_callback=None) -> Pipeline:
    pipeline = Pipeline(
        client,
        Mock(spec=StructuredLogger),
        status_callback=status_callback,
    )
    pipeline._current_job_id = "r1d-job"
    pipeline._current_stage_chain = ["txt2img"]
    pipeline._ensure_webui_true_ready = Mock()
    pipeline._check_webui_health_before_stage = Mock()
    return pipeline


def _set_short_stall_policy(monkeypatch) -> None:
    monkeypatch.setattr("src.pipeline.executor.PROGRESS_STALL_THRESHOLD_SEC", 0.01)
    monkeypatch.setattr("src.pipeline.executor.STALL_INTERRUPT_THRESHOLD_SEC", 0.02)
    monkeypatch.setattr("src.pipeline.executor.STALL_INTERRUPT_THRESHOLD_BY_STAGE", {})
    monkeypatch.setattr("src.pipeline.executor.POST_INTERRUPT_STALL_GRACE_SEC", 0.03)


@pytest.mark.parametrize(
    ("stop_after", "expected_restarts"),
    ((39.0, 0), (40.0, 1)),
)
def test_fake_clock_enforces_post_interrupt_grace(
    monkeypatch, stop_after: float, expected_restarts: int
) -> None:
    clock = _FakeClock()
    client = _BlockingGenerationClient()
    manager = _ProcessManager(client, managed=True)
    pipeline = _pipeline(client)
    managed_escalation = threading.Event()
    monkeypatch.setattr("src.pipeline.executor.time.monotonic", clock.monotonic)
    monkeypatch.setattr("src.pipeline.executor.PROGRESS_STALL_THRESHOLD_SEC", 5.0)
    monkeypatch.setattr("src.pipeline.executor.STALL_INTERRUPT_THRESHOLD_SEC", 10.0)
    monkeypatch.setattr("src.pipeline.executor.STALL_INTERRUPT_THRESHOLD_BY_STAGE", {})
    monkeypatch.setattr("src.pipeline.executor.POST_INTERRUPT_STALL_GRACE_SEC", 30.0)
    monkeypatch.setattr("src.pipeline.executor.get_global_webui_process_manager", lambda: manager)

    pipeline._poll_progress_loop(
        _ClockStopEvent(clock, stop_after=stop_after),
        1.0,
        None,
        "txt2img",
        managed_stall_escalation_event=managed_escalation,
    )

    assert client.interrupt_count == 1
    assert manager.restart_count == expected_restarts
    assert managed_escalation.is_set() is bool(expected_restarts)


def test_managed_wedge_restarts_once_and_returns_nonreplayable_unknown(monkeypatch) -> None:
    client = _BlockingGenerationClient()
    manager = _ProcessManager(client, managed=True)
    pipeline = _pipeline(client)
    _set_short_stall_policy(monkeypatch)
    monkeypatch.setattr("src.pipeline.executor.get_global_webui_process_manager", lambda: manager)

    with pytest.raises(PipelineStageError) as error:
        pipeline._generate_images_with_progress(
            "txt2img",
            {"prompt": "managed wedge", "steps": 20},
            poll_interval=0.01,
        )

    assert error.value.error.code is GenerateErrorCode.OUTCOME_UNKNOWN
    assert client.post_count == 1
    assert client.interrupt_count == 1
    assert manager.restart_count == 1


def test_request_return_during_grace_does_not_escalate(monkeypatch) -> None:
    client = _BlockingGenerationClient(release_on_interrupt=True)
    manager = _ProcessManager(client, managed=True)
    pipeline = _pipeline(client)
    _set_short_stall_policy(monkeypatch)
    monkeypatch.setattr("src.pipeline.executor.get_global_webui_process_manager", lambda: manager)

    result = pipeline._generate_images_with_progress(
        "txt2img",
        {"prompt": "returns during grace", "steps": 20},
        poll_interval=0.01,
    )

    assert result == {"images": ["image"], "info": {}, "stage": "txt2img", "timings": {}}
    assert client.post_count == 1
    assert client.interrupt_count == 1
    assert manager.restart_count == 0


def test_external_wedge_emits_once_without_process_mutation(monkeypatch) -> None:
    client = _BlockingGenerationClient()
    manager = _ProcessManager(client, managed=False)
    events: list[dict[str, object]] = []

    def observe_status(status: dict[str, object]) -> None:
        if status.get("event") == EXTERNAL_WEBUI_STALL_ACTION_REQUIRED:
            events.append(status)
            client.release.set()

    pipeline = _pipeline(client, status_callback=observe_status)
    _set_short_stall_policy(monkeypatch)
    monkeypatch.setattr("src.pipeline.executor.get_global_webui_process_manager", lambda: manager)

    with pytest.raises(PipelineStageError) as error:
        pipeline._generate_images_with_progress(
            "txt2img",
            {"prompt": "external wedge", "steps": 20},
            poll_interval=0.01,
        )

    assert error.value.error.code is GenerateErrorCode.OUTCOME_UNKNOWN
    assert client.post_count == 1
    assert client.interrupt_count == 1
    assert manager.restart_count == 0
    assert manager.start_count == 0
    assert manager.stop_count == 0
    assert len(events) == 1
    assert events[0]["job_id"] == "r1d-job"
    assert events[0]["recovery_mode"] == "external_manual"
    assert events[0]["interrupt_sent"] is True
    assert "Restart or stop the external A1111" in str(events[0]["action"])


def test_outcome_unknown_is_not_runner_retried_and_next_job_can_run() -> None:
    queue = JobQueue()
    calls: list[str] = []

    def run(job):
        calls.append(job.job_id)
        if job.job_id == "wedged":
            raise PipelineStageError(
                GenerateError(
                    code=GenerateErrorCode.OUTCOME_UNKNOWN,
                    message="request may have executed",
                    stage="txt2img",
                )
            )
        return {"success": True}

    runner = SingleNodeJobRunner(queue, run, poll_interval=0.01)
    wedged = make_queue_job("wedged")
    subsequent = make_queue_job("subsequent")
    queue.submit(wedged)
    queue.submit(subsequent)

    with pytest.raises(PipelineStageError):
        runner.run_once(wedged)
    result = runner.run_once(subsequent)

    assert calls == ["wedged", "subsequent"]
    assert queue.get_job("wedged").status is JobStatus.FAILED
    assert queue.get_job("subsequent").status is JobStatus.COMPLETED
    assert result["success"] is True
