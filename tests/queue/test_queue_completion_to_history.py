from __future__ import annotations

from pathlib import Path
import time
from typing import Any

from src.api.client import WebUIUnavailableError
from src.queue.job_model import Job, JobPriority, JobStatus
from src.queue.job_queue import JobQueue
from src.queue.job_history_store import JSONLJobHistoryStore
from src.queue.single_node_runner import SingleNodeJobRunner


def _build_history_queue(tmp_path: Path) -> tuple[JobQueue, JSONLJobHistoryStore]:
    history_store = JSONLJobHistoryStore(tmp_path / "history.jsonl")
    return JobQueue(history_store=history_store), history_store


def test_successful_job_moves_to_history(tmp_path: Path) -> None:
    queue, history_store = _build_history_queue(tmp_path)

    executed: list[str] = []

    def execute(job: Job) -> dict[str, Any]:
        executed.append(job.job_id)
        return {"status": "success"}

    runner = SingleNodeJobRunner(queue, execute, poll_interval=0.01)
    job = Job("success-job", priority=JobPriority.NORMAL)
    queue.submit(job)

    runner.start()
    time.sleep(0.05)
    runner.stop()

    assert executed == ["success-job"]
    assert not queue.list_jobs()

    entry = history_store.get_job(job.job_id)
    assert entry is not None
    assert entry.status == JobStatus.COMPLETED
    assert entry.error_message is None


def test_webui_down_marks_job_failed(tmp_path: Path) -> None:
    queue, history_store = _build_history_queue(tmp_path)

    def fail(job: Job) -> dict[str, Any]:
        raise WebUIUnavailableError(
            endpoint="/sdapi/v1/txt2img",
            method="POST",
            stage="txt2img",
            reason="connection refused",
        )

    runner = SingleNodeJobRunner(queue, fail, poll_interval=0.01)
    job = Job("fail-job", priority=JobPriority.NORMAL)
    queue.submit(job)

    runner.start()
    time.sleep(0.05)
    runner.stop()

    assert not queue.list_jobs()

    entry = history_store.get_job(job.job_id)
    assert entry is not None
    assert entry.status == JobStatus.FAILED
    assert entry.error_message is not None
    assert "connection refused" in entry.error_message

