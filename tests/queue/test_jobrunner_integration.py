from __future__ import annotations

import time
from pathlib import Path

from src.queue.job_model import Job, JobPriority, JobStatus
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from src.queue.single_node_runner import SingleNodeJobRunner
from tests.helpers.njr_factory import make_queue_job


def test_jobrunner_integration_updates_status_and_result():
    queue = JobQueue()
    seen = []

    def _execute(job: Job):
        seen.append(job.job_id)
        return {"done": True}

    runner = SingleNodeJobRunner(queue, _execute, poll_interval=0.01)
    job = make_queue_job("j1", priority=JobPriority.NORMAL)
    job.payload = lambda: None
    queue.submit(job)
    runner.start()
    time.sleep(0.05)
    runner.stop()
    persisted = queue.get_job(job.job_id)
    assert persisted is not None
    assert persisted.status == JobStatus.COMPLETED
    assert persisted.result is not None


def test_runner_executes_restored_jobs() -> None:
    queue = JobQueue()
    executed: list[str] = []

    def _execute(job: Job):
        executed.append(job.job_id)
        return {"restored": True, "success": True}

    runner = SingleNodeJobRunner(queue, _execute, poll_interval=0.01)
    job = make_queue_job("restored-job", priority=JobPriority.NORMAL)
    job.payload = lambda: {"restored": True}
    queue.restore_jobs([job])

    runner.start()
    time.sleep(0.05)
    runner.stop()

    assert "restored-job" in executed
    assert job.status == JobStatus.COMPLETED
    assert job.result and job.result.get("success") is True


def test_runner_does_not_dequeue_while_queue_paused() -> None:
    queue = JobQueue()
    executed: list[str] = []

    def _execute(job: Job):
        executed.append(job.job_id)
        return {"success": True}

    queue.submit(make_queue_job("paused-job", priority=JobPriority.NORMAL))
    queue.pause()
    runner = SingleNodeJobRunner(queue, _execute, poll_interval=0.01)

    runner.start()
    time.sleep(0.05)
    runner.stop()

    assert executed == []
    assert queue.get_job("paused-job").status == JobStatus.QUEUED

    queue.resume()
    runner = SingleNodeJobRunner(queue, _execute, poll_interval=0.01)
    runner.start()
    time.sleep(0.05)
    runner.stop()

    assert executed == ["paused-job"]


def test_run_once_cancel_return_to_queue_requeues_job() -> None:
    queue = JobQueue()
    runner: SingleNodeJobRunner

    def _execute(job: Job):
        runner.cancel_current(return_to_queue=True)
        return {
            "success": True,
            "stage_events": [{"stage": "txt2img", "event": "exit"}],
            "variants": [{"path": "out/test.png"}],
        }

    runner = SingleNodeJobRunner(queue, _execute, poll_interval=0.01)
    job = make_queue_job("return-job", priority=JobPriority.NORMAL)
    queue.submit(job)

    result = runner.run_once(job)

    assert result is not None
    assert job.status == JobStatus.QUEUED
    assert job.execution_metadata.return_to_queue_count == 1
    assert job.execution_metadata.stage_checkpoints == []


def test_cancelled_job_does_not_publish_late_success(tmp_path: Path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    queue = JobQueue(repository=repository)
    acceptance_output = tmp_path / "acceptance-owned.png"
    unrelated_output = tmp_path / "unrelated.png"
    unrelated_output.write_bytes(b"unrelated")
    runner_statuses: list[JobStatus] = []

    def _execute(job: Job) -> dict[str, object]:
        acceptance_output.write_bytes(b"late backend output")
        cancelled = queue.mark_cancelled(job.job_id, "cancel_requested")
        assert cancelled is job
        return {
            "run_id": job.job_id,
            "success": True,
            "stage_events": [{"stage": "txt2img", "phase": "exit"}],
            "variants": [{"path": str(acceptance_output)}],
        }

    runner = SingleNodeJobRunner(
        queue,
        _execute,
        poll_interval=0.01,
        on_status_change=lambda _job, status: runner_statuses.append(status),
    )
    job = make_queue_job("cancel-publication-race", priority=JobPriority.NORMAL)
    queue.submit(job)

    returned_result = runner.run_once(job)
    persisted = repository.get_job_model(job.job_id)

    assert returned_result is None
    assert persisted is not None
    assert persisted.status == JobStatus.CANCELLED
    assert persisted.error_message == "cancel_requested"
    assert persisted.result is None
    assert repository.get_artifact_references(job.job_id) == []
    assert persisted.execution_metadata.stage_checkpoints == []
    assert JobStatus.COMPLETED not in runner_statuses
    assert acceptance_output.is_file()
    assert unrelated_output.read_bytes() == b"unrelated"


def test_non_cancelled_job_publishes_result_and_final_checkpoint(tmp_path: Path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    queue = JobQueue(repository=repository)
    output = tmp_path / "success.png"
    output.write_bytes(b"success")

    def _execute(job: Job) -> dict[str, object]:
        return {
            "run_id": job.job_id,
            "success": True,
            "stage_events": [{"stage": "txt2img", "phase": "exit"}],
            "variants": [{"path": str(output)}],
        }

    runner = SingleNodeJobRunner(queue, _execute, poll_interval=0.01)
    job = make_queue_job("successful-publication", priority=JobPriority.NORMAL)
    queue.submit(job)

    runner.run_once(job)
    persisted = repository.get_job_model(job.job_id)

    assert persisted is not None
    assert persisted.status == JobStatus.COMPLETED
    assert persisted.result is not None and persisted.result["success"] is True
    assert repository.get_artifact_references(job.job_id) == [str(output)]
    assert [item.stage_name for item in persisted.execution_metadata.stage_checkpoints] == [
        "final_output"
    ]
