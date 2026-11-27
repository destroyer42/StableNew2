"""RUN-LEAN: a Cancel must reach the running job, so the queue does not wait for work nobody wants."""

from __future__ import annotations

import time
from unittest.mock import Mock

import pytest

from src.controller.job_execution_controller import JobExecutionController
from src.controller.runtime_state import CancellationError, CancelToken
from src.pipeline.executor import Pipeline
from src.pipeline.replay_engine import ReplayEngine
from tests.helpers.job_helpers import make_test_job_from_njr, make_test_njr


class _RunnerSpy:
    def __init__(self) -> None:
        self.tokens: list[object] = []

    def run_njr(self, record, cancel_token=None, run_plan=None, checkpoint_callback=None):
        self.tokens.append(cancel_token)
        return {"success": True}


def _job():
    job = make_test_job_from_njr(make_test_njr())
    job._cancel_token = CancelToken()
    return job


def test_replay_hands_the_jobs_own_cancel_token_to_the_runner() -> None:
    spy, job = _RunnerSpy(), _job()

    ReplayEngine(spy).replay_njr(job._normalized_record, job=job)

    assert spy.tokens == [job._cancel_token]


def test_replay_without_a_job_token_keeps_the_engine_token() -> None:
    spy, token = _RunnerSpy(), CancelToken()
    job = _job()
    job._cancel_token = None

    ReplayEngine(spy, cancel_token=token).replay_njr(job._normalized_record, job=job)
    ReplayEngine(spy, cancel_token=token).replay_njr(job._normalized_record)

    assert spy.tokens == [token, token]


def test_the_queue_execution_path_hands_over_the_jobs_cancel_token() -> None:
    spy, job = _RunnerSpy(), _job()
    controller = JobExecutionController(replay_runner=spy, execute_job=lambda _job: {})

    controller._run_job_callback(job)

    assert spy.tokens == [job._cancel_token]


def _pipeline(monkeypatch, generate) -> tuple[Pipeline, Mock]:
    client = Mock()
    client.get_progress.return_value = None
    pipeline = Pipeline(client, Mock())
    monkeypatch.setattr(pipeline, "_generate_images", generate)
    return pipeline, client


def test_a_cancel_during_preparation_dispatches_nothing(monkeypatch) -> None:
    dispatched: list[str] = []
    pipeline, _client = _pipeline(monkeypatch, lambda stage, payload: dispatched.append(stage))
    token = CancelToken()
    token.cancel()

    with pytest.raises(CancellationError):
        pipeline._generate_images_with_progress("txt2img", {}, poll_interval=0.01, cancel_token=token)

    assert dispatched == []


def test_the_interrupt_is_repeated_while_the_cancelled_request_is_still_running(monkeypatch) -> None:
    """The first interrupt can land before WebUI has the request, which then clears it and generates in full."""

    token = CancelToken()
    client_box: dict[str, Mock] = {}

    def generate(stage, payload):
        token.cancel()
        deadline = time.monotonic() + 5.0
        while client_box["client"].interrupt.call_count < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        return {"images": []}

    pipeline, client_box["client"] = _pipeline(monkeypatch, generate)

    with pytest.raises(CancellationError):
        pipeline._generate_images_with_progress("txt2img", {}, poll_interval=0.01, cancel_token=token)

    assert client_box["client"].interrupt.call_count >= 2
