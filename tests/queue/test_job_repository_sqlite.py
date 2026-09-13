from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from src.pipeline.cli_njr_builder import build_cli_njr
from src.queue.job_history_store import INTERRUPTED_RESTART_ACTION_REQUIRED
from src.queue.job_model import Job, JobStatus, RetryAttempt, StageCheckpoint
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from src.queue.single_node_runner import SingleNodeJobRunner
from src.utils.error_envelope_v2 import UnifiedErrorEnvelope


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


def test_running_job_becomes_action_required_after_restart(tmp_path: Path) -> None:
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
    assert recovered.status == JobStatus.FAILED
    assert recovered.execution_metadata.last_control_action == (
        "restart_interrupted_action_required"
    )
    assert recovered.execution_metadata.return_to_queue_count == 0
    assert recovered.error_envelope is not None
    assert recovered.error_envelope.error_type == INTERRUPTED_RESTART_ACTION_REQUIRED
    assert recovered.error_envelope.context == {
        "recovery_identifier": INTERRUPTED_RESTART_ACTION_REQUIRED,
        "action_required": True,
        "generation_outcome": "ambiguous",
        "automatic_replay": False,
    }
    assert "not automatically replayed" in recovered.error_message
    assert restarted.list_active_jobs_ordered() == []
    assert restarted.get_next_job() is None
    executed: list[str] = []
    runner = SingleNodeJobRunner(
        restarted,
        lambda job: executed.append(job.job_id) or {"success": True},
    )
    assert runner.run_next_once() is False
    assert executed == []

    history_entry = restarted_repository.get_job("interrupted")
    assert history_entry is not None
    assert history_entry.status == JobStatus.FAILED
    assert history_entry.error_envelope is not None
    assert history_entry.error_envelope.error_type == INTERRUPTED_RESTART_ACTION_REQUIRED


def test_interrupted_recovery_preserves_execution_evidence(tmp_path: Path) -> None:
    path = tmp_path / "jobs.sqlite3"
    repository = JobRepository(path)
    queue = JobQueue(repository=repository)
    job = _job("interrupted-child", parent="parent")
    queue.submit(job)
    queue.mark_running(job.job_id)
    job.execution_metadata.external_pids = [4321]
    job.execution_metadata.retry_attempts.append(
        RetryAttempt(stage="txt2img", attempt_index=1, max_attempts=2, reason="timeout")
    )
    job.execution_metadata.stage_checkpoints.append(
        StageCheckpoint(
            stage_name="txt2img",
            output_paths=["output/checkpoint.png"],
            metadata={"seed": 42},
        )
    )
    job.error_envelope = UnifiedErrorEnvelope(
        error_type="BackendDiagnostic",
        subsystem="pipeline",
        severity="WARNING",
        message="last backend diagnostic",
        cause=None,
        stack="backend-stack",
        job_id=job.job_id,
        stage="txt2img",
        retry_info={"attempt": 1},
    )
    queue.persist_runtime_state(job)
    persisted_running = repository.transition_job(
        job,
        JobStatus.RUNNING,
        result={
            "variants": [{"path": "output/possibly-produced.png"}],
            "metadata": {"backend_request_id": "request-7"},
        },
    )
    original_snapshot = persisted_running.snapshot
    original_created_at = persisted_running.created_at
    original_started_at = persisted_running.started_at
    original_storage_identity = tuple(
        repository._connection.execute(  # noqa: SLF001 - persistence contract evidence
            """
            SELECT njr_fingerprint, queue_order, queued_at
            FROM jobs WHERE job_id = ?
            """,
            (job.job_id,),
        ).fetchone()
    )
    repository.close()

    with JobRepository(path) as restarted_repository:
        restarted = JobQueue(repository=restarted_repository)
        recovered = restarted.get_job(job.job_id)
        assert recovered is not None
        assert recovered.status == JobStatus.FAILED
        assert recovered.snapshot == original_snapshot
        assert recovered.created_at == original_created_at
        assert recovered.started_at == original_started_at
        assert recovered.completed_at is not None
        recovered_storage_identity = tuple(
            restarted_repository._connection.execute(  # noqa: SLF001
                """
                SELECT njr_fingerprint, queue_order, queued_at
                FROM jobs WHERE job_id = ?
                """,
                (job.job_id,),
            ).fetchone()
        )
        assert recovered_storage_identity == original_storage_identity
        assert recovered.result == {
            "variants": [{"path": "output/possibly-produced.png"}],
            "metadata": {"backend_request_id": "request-7"},
        }
        assert restarted_repository.get_artifact_references(job.job_id) == [
            "output/possibly-produced.png"
        ]
        assert restarted_repository.get_lineage(job.job_id) == (
            "parent",
            "artifact-parent",
        )
        assert recovered.execution_metadata.external_pids == [4321]
        assert recovered.execution_metadata.retry_attempts[0].reason == "timeout"
        assert recovered.execution_metadata.stage_checkpoints[0].metadata == {"seed": 42}
        assert recovered.execution_metadata.return_to_queue_count == 0
        assert recovered.error_envelope is not None
        assert recovered.error_envelope.stage == "txt2img"
        assert recovered.error_envelope.retry_info == {"attempt": 1}
        assert recovered.error_envelope.context["prior_error_envelope"]["error_type"] == (
            "BackendDiagnostic"
        )


def test_restart_keeps_queued_order_and_excludes_interrupted_job(tmp_path: Path) -> None:
    path = tmp_path / "jobs.sqlite3"
    repository = JobRepository(path)
    queue = JobQueue(repository=repository)
    queue.submit(_job("first"))
    queue.submit(_job("interrupted"))
    queue.submit(_job("second"))
    queue.mark_running("interrupted")
    queue.pause()
    repository.close()

    restarted_repository = JobRepository(path)
    restarted = JobQueue(repository=restarted_repository)
    assert restarted.is_paused() is True
    assert [job.job_id for job in restarted.list_active_jobs_ordered()] == ["first", "second"]
    assert restarted.get_next_job() is None
    restarted.resume()
    assert restarted.get_next_job().job_id == "first"
    assert restarted.get_next_job().job_id == "second"
    assert restarted.get_next_job() is None


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
