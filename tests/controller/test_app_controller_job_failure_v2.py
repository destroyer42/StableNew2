"""Tests for structured job failure surfacing in AppController."""

from __future__ import annotations

from typing import Any, Callable

import pytest

from src.controller.app_controller import AppController
from src.gui.app_state_v2 import AppStateV2
from src.queue.job_model import Job, JobStatus
from src.utils.error_envelope_v2 import wrap_exception


class DummyJobService:
    """Minimal JobService stub used for AppController tests."""

    EVENT_QUEUE_UPDATED = "queue_updated"
    EVENT_QUEUE_STATUS = "queue_status"
    EVENT_JOB_STARTED = "job_started"
    EVENT_JOB_FINISHED = "job_finished"
    EVENT_JOB_FAILED = "job_failed"
    EVENT_QUEUE_EMPTY = "queue_empty"

    def register_callback(self, *_: Any, **__: Any) -> None:
        pass


def _build_controller() -> AppController:
    job_service = DummyJobService()
    controller = AppController(None, threaded=False, job_service=job_service)
    controller.app_state = AppStateV2()
    return controller


def test_structured_job_failure_updates_state(monkeypatch: pytest.MonkeyPatch) -> None:
    controller = _build_controller()
    job = Job(job_id="job-1", pipeline_config=None)
    job.status = JobStatus.FAILED
    envelope = wrap_exception(Exception("boom"), subsystem="pipeline", job_id=job.job_id)
    job.error_envelope = envelope
    captured: dict[str, Any] = {"shown": False}

    def fake_show_modal(env: Any) -> None:
        captured["shown"] = True
        captured["envelope"] = env

    monkeypatch.setattr(controller, "_show_structured_error_modal", fake_show_modal)
    controller._on_job_failed(job)

    assert controller._last_error_envelope is envelope
    assert controller.state.last_error == envelope.message
    assert controller.app_state.last_error == envelope.message
    assert captured["shown"]
