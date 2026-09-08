from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from src.pipeline.cli_njr_builder import build_cli_njr
from src.queue.job_model import Job, JobStatus, RetryAttempt, StageCheckpoint
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository


def _job(job_id: str, *, parent: str | None = None) -> Job:
    record = build_cli_njr(
        prompt=f"prompt {job_id}",
        batch_size=1,
        run_name=job_id,
        config={
            "txt2img": {
                "model": "test.safetensors",
                "steps": 4,
                "cfg_scale": 5.0,
                "width": 64,
                "height": 64,
            }
        },
    )
    if parent:
        record = replace(
            record,
            source=replace(
                record.source,
                parent_job_id=parent,
                parent_artifact_id="artifact-parent",
            ),
        )
    job = Job(job_id=record.job_id, snapshot={"normalized_job": record.to_dict()})
    job._normalized_record = record  # type: ignore[attr-defined]
    return job


def test_queued_job_and_order_survive_restart(tmp_path: Path) -> None:
    path = tmp_path / "jobs.sqlite3"
    repository = JobRepository(path)
    queue = JobQueue(repository=repository)
    queue.submit(_job("first"))
    queue.submit(_job("second"))
    queue.move_up("second")
    repository.close()

    restarted_repository = JobRepository(path)
    restarted = JobQueue(repository=restarted_repository)
    assert [job.job_id for job in restarted.list_active_jobs_ordered()] == ["second", "first"]


def test_running_job_is_safely_requeued_after_restart(tmp_path: Path) -> None:
    path = tmp_path / "jobs.sqlite3"
    repository = JobRepository(path)
    queue = JobQueue(repository=repository)
    queue.submit(_job("interrupted"))
    queue.mark_running("interrupted")
    repository.close()

    restarted_repository = JobRepository(path)
    restarted = JobQueue(repository=restarted_repository)
    recovered = restarted.get_job("interrupted")
    assert recovered is not None
    assert recovered.status == JobStatus.QUEUED
    assert recovered.execution_metadata.last_control_action == "restart_requeue"
    assert recovered.execution_metadata.return_to_queue_count == 1


@pytest.mark.parametrize(
    ("status", "error"),
    [(JobStatus.COMPLETED, None), (JobStatus.FAILED, "boom"), (JobStatus.CANCELLED, "stop")],
)
def test_terminal_history_survives_restart(
    tmp_path: Path, status: JobStatus, error: str | None
) -> None:
    path = tmp_path / f"{status.value}.sqlite3"
    repository = JobRepository(path)
    queue = JobQueue(repository=repository)
    queue.submit(_job(status.value))
    if status != JobStatus.CANCELLED:
        queue.mark_running(status.value)
    if status == JobStatus.COMPLETED:
        queue.mark_completed(status.value, {"image_paths": ["output/image.png"]})
    elif status == JobStatus.FAILED:
        queue.mark_failed(status.value, error or "failed", {"code": "pipeline_failed"})
    else:
        queue.mark_cancelled(status.value, error)
    repository.close()

    with JobRepository(path) as restarted:
        entry = restarted.get_job(status.value)
        assert entry is not None
        assert entry.status == status
        assert entry.error_message == error
        if status == JobStatus.COMPLETED:
            assert restarted.get_artifact_references(status.value) == ["output/image.png"]


def test_retry_checkpoint_result_and_lineage_survive(tmp_path: Path) -> None:
    path = tmp_path / "jobs.sqlite3"
    repository = JobRepository(path)
    queue = JobQueue(repository=repository)
    job = _job("child", parent="parent")
    queue.submit(job)
    queue.mark_running(job.job_id)
    job.execution_metadata.retry_attempts.append(
        RetryAttempt(stage="txt2img", attempt_index=2, max_attempts=2, reason="restart")
    )
    job.execution_metadata.stage_checkpoints.append(
        StageCheckpoint(stage_name="txt2img", output_paths=["output/checkpoint.png"])
    )
    queue.persist_runtime_state(job)
    queue.mark_completed(job.job_id, {"variants": [{"path": "output/final.png"}]})
    repository.close()

    with JobRepository(path) as restarted:
        restored = restarted.get_job_model("child")
        assert restored is not None
        assert restored.execution_metadata.retry_attempts[0].attempt_index == 2
        assert restored.execution_metadata.stage_checkpoints[0].output_paths == [
            "output/checkpoint.png"
        ]
        assert restored.result == {"variants": [{"path": "output/final.png"}]}
        assert restarted.get_artifact_references("child") == ["output/final.png"]
        assert restarted.get_lineage("child") == ("parent", "artifact-parent")


def test_failed_transition_rolls_back_without_partial_state(tmp_path: Path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    queue = JobQueue(repository=repository)
    job = _job("atomic")
    queue.submit(job)
    with repository.transaction() as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_running BEFORE UPDATE OF status ON jobs
            WHEN NEW.status = 'running'
            BEGIN SELECT RAISE(ABORT, 'injected transition failure'); END
            """
        )
    with pytest.raises(sqlite3.IntegrityError, match="injected transition failure"):
        repository.transition_job(job, JobStatus.RUNNING)
    persisted = repository.get_job_model("atomic")
    assert persisted is not None
    assert persisted.status == JobStatus.QUEUED
    assert persisted.completed_at is None
