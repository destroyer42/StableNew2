from __future__ import annotations

from types import SimpleNamespace
import logging
from typing import Any

import pytest

from src.controller.job_execution_controller import JobExecutionController
from src.queue.job_model import Job, JobPriority


def _make_job(job_id: str) -> Job:
    job = Job(job_id=job_id, priority=JobPriority.NORMAL)
    return job


def test_run_job_callback_missing_normalized_record_raises(caplog) -> None:
    controller = JobExecutionController(replay_runner=SimpleNamespace(run_njr=lambda record: {}))
    job = _make_job("missing")
    caplog.set_level(logging.ERROR)

    with pytest.raises(ValueError) as excinfo:
        controller._run_job_callback(job)

    assert "Missing normalized record" in str(excinfo.value)
    assert any("JOB_EXEC_ERROR | Missing normalized record" in record.message for record in caplog.records)


class _FailReplay:
    def replay_njr(self, record: object) -> dict:
        raise RuntimeError("replay failed")

    def run_njr(self, record: object, *args: Any, **kwargs: Any) -> dict:
        return self.replay_njr(record)


def test_run_job_callback_replay_exception_logs_and_raises(caplog) -> None:
    controller = JobExecutionController(replay_runner=_FailReplay())
    job = _make_job("replay-error")
    job._normalized_record = SimpleNamespace(job_id="replay-error")
    caplog.set_level(logging.INFO)

    with pytest.raises(RuntimeError) as excinfo:
        controller._run_job_callback(job)

    assert "NJR execution failed" in str(excinfo.value)
    assert any("JOB_EXEC_REPLAY" in record.message for record in caplog.records)
    assert any("JOB_EXEC_ERROR | NJR execution failed" in record.message for record in caplog.records)
