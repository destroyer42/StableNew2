from __future__ import annotations

import time
from pathlib import Path

import pytest

from src.controller.job_execution_controller import JobExecutionController
from src.controller.job_history_service import JobHistoryService
from src.queue.job_model import JobStatus
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from src.utils.error_envelope_v2 import get_attached_envelope, wrap_exception
from tests.helpers.njr_factory import make_queue_job


def _wait_until(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not reached before timeout")


def _fail_at_txt2img() -> None:
    error = RuntimeError("deterministic txt2img failure")
    wrap_exception(error, subsystem="fake_txt2img", stage="txt2img")
    raise error


def test_deterministic_txt2img_failure_is_durable_without_artifact(tmp_path: Path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    queue = JobQueue(repository=repository)
    from src.queue.single_node_runner import SingleNodeJobRunner

    runner = SingleNodeJobRunner(queue, lambda _job: _fail_at_txt2img(), poll_interval=0.01)
    job = make_queue_job("deterministic-failure")
    original_njr = job._normalized_record
    queue.submit(job)

    with pytest.raises(RuntimeError, match="deterministic txt2img failure"):
        runner.run_once(job)

    stored = repository.get_job_model(job.job_id)
    history = repository.get_job(job.job_id)
    assert stored is not None
    assert history is not None
    assert stored.status is JobStatus.FAILED
    assert history.status is JobStatus.FAILED
    assert stored.error_message == "deterministic txt2img failure"
    assert stored.error_envelope is not None
    assert stored.error_envelope.stage == "txt2img"
    assert stored.result is None
    assert repository.get_artifact_references(job.job_id) == []
    assert original_njr is not None
    assert stored._normalized_record is not None
    assert stored._normalized_record.to_dict() == original_njr.to_dict()


def test_retry_is_new_lineage_and_preserves_authorized_workload(tmp_path: Path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    queue = JobQueue(repository=repository)
    attempts = []

    def execute(record):
        attempts.append(record)
        if len(attempts) == 1:
            _fail_at_txt2img()
        return {"success": True, "variants": [{"path": "output/retry.png"}]}

    controller = JobExecutionController(
        execute_job=execute,
        queue=queue,
        restore_state=False,
    )
    controller.set_auto_run_enabled(False)
    history = JobHistoryService(queue, repository, job_controller=controller)
    original = make_queue_job(
        "retry-source",
        positive_prompt="authorized positive",
        negative_prompt="authorized negative",
        base_model="checkpoint.safetensors",
        sampler_name="DPM++ 2M",
        steps=23,
        cfg_scale=6.5,
        width=640,
        height=768,
        seed=606060,
    )
    queue.submit(original)

    with pytest.raises(RuntimeError):
        controller.get_runner().run_once(original)

    retry_id = history.retry_job(original.job_id)
    assert retry_id is not None
    retry_job = queue.get_job(retry_id)
    assert retry_job is not None
    controller.get_runner().run_once(retry_job)

    failed = repository.get_job_model(original.job_id)
    succeeded = repository.get_job_model(retry_id)
    assert failed is not None and failed.status is JobStatus.FAILED
    assert succeeded is not None and succeeded.status is JobStatus.COMPLETED
    assert succeeded.result is not None
    assert succeeded.result["success"] is True
    assert succeeded.result["variants"][0]["output_path"] == "output/retry.png"
    assert repository.get_artifact_references(retry_id) == ["output/retry.png"]

    source = original._normalized_record
    replay = retry_job._normalized_record
    assert source is not None and replay is not None
    assert replay.job_id != source.job_id
    assert replay.source.parent_job_id == source.job_id
    assert replay.source.kind.value == "history_replay"
    assert replay.workload == source.workload
    assert replay.stages == source.stages
    assert replay.output_plan == source.output_plan
    assert replay.provenance.seed == source.provenance.seed
    assert attempts[0].workload == attempts[1].workload


def test_fifo_order_and_failure_do_not_wedge_following_job(tmp_path: Path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    queue = JobQueue(repository=repository)
    calls: list[str] = []

    def execute(job):
        calls.append(job.job_id)
        if job.job_id == "fifo-a":
            _fail_at_txt2img()
        return {"success": True, "variants": [{"path": "output/fifo-b.png"}]}

    from src.queue.single_node_runner import SingleNodeJobRunner

    runner = SingleNodeJobRunner(queue, execute, poll_interval=0.01)
    queue.submit(make_queue_job("fifo-a"))
    queue.submit(make_queue_job("fifo-b"))
    runner.start()
    _wait_until(
        lambda: all(
            queue.repository.get_job_model(job_id).status
            in {JobStatus.FAILED, JobStatus.COMPLETED}
            for job_id in ("fifo-a", "fifo-b")
        )
    )
    runner.stop()

    assert calls == ["fifo-a", "fifo-b"]
    assert repository.get_job_model("fifo-a").status is JobStatus.FAILED
    assert repository.get_job_model("fifo-b").status is JobStatus.COMPLETED


def test_terminal_and_pending_records_survive_repository_reopen(tmp_path: Path) -> None:
    path = tmp_path / "jobs.sqlite3"
    repository = JobRepository(path)
    queue = JobQueue(repository=repository)
    completed = make_queue_job("reopen-completed")
    failed = make_queue_job("reopen-failed")
    pending_a = make_queue_job("reopen-pending-a")
    pending_b = make_queue_job("reopen-pending-b")
    for job in (completed, failed, pending_a, pending_b):
        queue.submit(job)
    queue.mark_running(completed.job_id)
    queue.mark_completed(completed.job_id, {"success": True, "variants": [{"path": "output/done.png"}]})
    queue.mark_running(failed.job_id)
    failed_error = RuntimeError("reopen failure")
    wrap_exception(failed_error, subsystem="fake_txt2img", stage="txt2img")
    failed.error_envelope = get_attached_envelope(failed_error)
    queue.mark_failed(failed.job_id, "reopen failure")
    repository.close()

    reopened_repository = JobRepository(path)
    reopened_queue = JobQueue(repository=reopened_repository)
    assert [job.job_id for job in reopened_queue.list_active_jobs_ordered()] == [
        "reopen-pending-a",
        "reopen-pending-b",
    ]
    completed_entry = reopened_repository.get_job("reopen-completed")
    failed_entry = reopened_repository.get_job("reopen-failed")
    assert completed_entry is not None and completed_entry.status is JobStatus.COMPLETED
    assert failed_entry is not None and failed_entry.status is JobStatus.FAILED
    assert completed_entry.result == {
        "success": True,
        "variants": [{"path": "output/done.png"}],
    }
    assert failed_entry.error_message == "reopen failure"
    assert reopened_repository.get_artifact_references("reopen-completed") == ["output/done.png"]

    executed: list[str] = []
    from src.queue.single_node_runner import SingleNodeJobRunner

    runner = SingleNodeJobRunner(
        reopened_queue,
        lambda job: executed.append(job.job_id) or {"success": True},
        poll_interval=0.01,
    )
    runner.run_once(reopened_queue.get_job("reopen-pending-a"))
    runner.run_once(reopened_queue.get_job("reopen-pending-b"))
    assert executed == ["reopen-pending-a", "reopen-pending-b"]
