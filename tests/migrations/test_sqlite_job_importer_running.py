"""PR-RUNTIME-NO-IMPLICIT-REPLAY: a legacy RUNNING record is imported as action-required, never runnable.

Whether an interrupted legacy job already dispatched or completed its generation is unknown, so the importer must not
make it eligible for automatic execution. Uses disposable JSON sources and SQLite repositories only.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from src.migrations.sqlite_job_importer import import_legacy_state
from src.pipeline.cli_njr_builder import build_cli_njr
from src.queue.job_history_store import INTERRUPTED_RESTART_ACTION_REQUIRED
from src.queue.job_model import JobStatus
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository


def _record(job_id: str) -> dict:
    njr = build_cli_njr(
        prompt="legacy prompt",
        batch_size=1,
        run_name=job_id,
        config={
            "txt2img": {
                "model": "legacy.safetensors",
                "steps": 10,
                "cfg_scale": 6.0,
                "width": 64,
                "height": 64,
            }
        },
    )
    return {
        "queue_id": job_id,
        "job_id": job_id,
        "status": "queued",
        "priority": 1,
        "njr_snapshot": {"normalized_job": njr.to_dict()},
    }


def _running_record(job_id: str = "interrupted") -> dict:
    item = _record(job_id)
    item.update(
        {
            "status": "running",
            "started_at": "2025-01-02T03:04:05",
            "updated_at": "2025-01-02T03:10:00",
            "result": {"image_paths": ["partial.png"]},
            "error_message": "legacy stage broke",
            "error_envelope": {
                "error_type": "LegacyStageError",
                "subsystem": "legacy",
                "severity": "ERROR",
                "message": "legacy stage warning",
                "stack": "",
                "job_id": job_id,
                "stage": "txt2img",
            },
            "execution_metadata": {
                "return_to_queue_count": 2,
                "stage_checkpoints": [
                    {
                        "stage_name": "txt2img",
                        "completed_at": 12.5,
                        "output_paths": ["stage.png"],
                        "metadata": {"image_count": 1},
                    }
                ],
            },
        }
    )
    return item


def _checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_queue(tmp_path: Path, *records: dict, name: str = "queue.json") -> Path:
    source = tmp_path / name
    source.write_text(json.dumps({"jobs": list(records)}), encoding="utf-8")
    return source


def _apply(database: Path, source: Path, *, dry_run: bool = False):
    return import_legacy_state(database_path=database, sources=[(source, "queue")], dry_run=dry_run)


def test_legacy_running_imports_non_runnable_and_action_required(tmp_path: Path) -> None:
    database = tmp_path / "jobs.sqlite3"

    result = _apply(database, _write_queue(tmp_path, _running_record()))

    assert result.validation["runnable_count"] == 0
    assert result.validation["status_by_identity"] == {"interrupted": "failed"}
    with JobRepository(database) as repository:
        job = repository.get_job_model("interrupted")
        assert job is not None and job.status is JobStatus.FAILED
        envelope = job.error_envelope
        assert envelope is not None
        assert envelope.error_type == INTERRUPTED_RESTART_ACTION_REQUIRED
        assert envelope.context["action_required"] is True
        assert envelope.context["generation_outcome"] == "ambiguous"
        assert envelope.context["automatic_replay"] is False
        assert envelope.context["legacy_original_status"] == "running"
        assert envelope.context["prior_error_message"] == "legacy stage broke"
        assert envelope.context["prior_error_envelope"]["error_type"] == "LegacyStageError"
        assert "unknown" in (job.error_message or "")
        assert job.execution_metadata.last_control_action == "restart_interrupted_action_required"
        # No requeue happened, so none is recorded: the legacy count is carried over unchanged.
        assert job.execution_metadata.return_to_queue_count == 2


def test_legacy_running_preserves_identity_and_evidence(tmp_path: Path) -> None:
    record = _running_record()
    database = tmp_path / "jobs.sqlite3"

    _apply(database, _write_queue(tmp_path, record))

    with JobRepository(database) as repository:
        job = repository.get_job_model("interrupted")
        assert job is not None
        assert job.job_id == "interrupted"
        assert job._normalized_record is not None and job._normalized_record.job_id == "interrupted"
        assert job.snapshot["normalized_job"] == record["njr_snapshot"]["normalized_job"]
        assert job.result == {"image_paths": ["partial.png"]}
        assert repository.get_artifact_references("interrupted") == ["partial.png"]
        assert [c.stage_name for c in job.execution_metadata.stage_checkpoints] == ["txt2img"]
        assert job.execution_metadata.stage_checkpoints[0].output_paths == ["stage.png"]
        assert job.started_at == datetime(2025, 1, 2, 3, 4, 5)
        assert job.updated_at == datetime(2025, 1, 2, 3, 10, 0)
        assert job.source == "legacy_import"


def test_dry_run_reports_running_as_terminal_not_runnable_and_writes_nothing(
    tmp_path: Path,
) -> None:
    source = _write_queue(tmp_path, _running_record(), _record("waiting"))
    database = tmp_path / "jobs.sqlite3"
    before = _checksum(source)

    result = _apply(database, source, dry_run=True)

    assert result.analysis.expected_runnable == 1
    assert result.analysis.expected_terminal == 1
    assert not database.exists()
    assert not (tmp_path / "migration_backups").exists()
    assert _checksum(source) == before


def test_running_import_is_backup_first_and_idempotent(tmp_path: Path) -> None:
    source = _write_queue(tmp_path, _running_record())
    database = tmp_path / "jobs.sqlite3"

    first = _apply(database, source)
    with JobRepository(database) as repository:
        stored = repository.get_job_model("interrupted")
        assert stored is not None
        first_state = (stored.status, stored.error_message, stored.completed_at)
    second = _apply(database, source)

    assert first.backup_directory is not None
    assert (Path(first.backup_directory) / "manifest.json").exists()
    assert second.imported == []
    assert second.analysis.duplicates == ["interrupted"]
    with JobRepository(database) as repository:
        assert repository.count() == 1
        job = repository.get_job_model("interrupted")
        assert job is not None
        assert (job.status, job.error_message, job.completed_at) == first_state


def test_existing_imported_records_are_not_changed(tmp_path: Path) -> None:
    database = tmp_path / "jobs.sqlite3"
    _apply(database, _write_queue(tmp_path, _record("earlier")))
    with JobRepository(database) as repository:
        earlier = repository.get_job_model("earlier")
        assert earlier is not None
        snapshot = (earlier.status, earlier.error_message, earlier.execution_metadata)

    # The same identity re-presented as RUNNING must not rewrite what is already stored.
    second = _write_queue(tmp_path, _record("earlier"), _running_record(), name="second.json")
    _apply(database, second)

    with JobRepository(database) as repository:
        earlier = repository.get_job_model("earlier")
        assert earlier is not None
        assert (earlier.status, earlier.error_message, earlier.execution_metadata) == snapshot
        assert repository.count() == 2


@pytest.mark.parametrize(
    ("legacy", "expected"),
    [
        ("pending", JobStatus.QUEUED),
        ("paused", JobStatus.QUEUED),
        ("queued", JobStatus.QUEUED),
        ("completed", JobStatus.COMPLETED),
        ("failed", JobStatus.FAILED),
        ("cancelled", JobStatus.CANCELLED),
        ("canceled", JobStatus.CANCELLED),
    ],
)
def test_other_legacy_statuses_keep_their_semantics(
    tmp_path: Path, legacy: str, expected: JobStatus
) -> None:
    item = _record("other")
    item["status"] = legacy
    database = tmp_path / "jobs.sqlite3"

    _apply(database, _write_queue(tmp_path, item))

    with JobRepository(database) as repository:
        job = repository.get_job_model("other")
        assert job is not None and job.status is expected
        assert job.error_envelope is None
        assert job.execution_metadata.return_to_queue_count == 0
        assert job.execution_metadata.last_control_action is None


def test_failed_running_import_rolls_back_without_corrupting_existing_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "jobs.sqlite3"
    _apply(database, _write_queue(tmp_path, _record("keep")))
    before = _checksum(database)
    source = _write_queue(
        tmp_path, _running_record("r1"), _running_record("r2"), name="second.json"
    )
    original = JobRepository._insert_imported_job
    calls = 0

    def fail_second(self, connection, job):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise sqlite3.IntegrityError("injected import failure")
        return original(self, connection, job)

    monkeypatch.setattr(JobRepository, "_insert_imported_job", fail_second)
    with pytest.raises(sqlite3.IntegrityError):
        _apply(database, source)

    assert _checksum(database) == before
    with JobRepository(database) as repository:
        assert repository.identities() == {"keep"}


def test_reopening_repository_never_dispatches_imported_interrupted_job(tmp_path: Path) -> None:
    database = tmp_path / "jobs.sqlite3"
    _apply(database, _write_queue(tmp_path, _running_record()))

    for _ in range(2):  # recovery and claim paths must both leave it untouched across restarts
        with JobRepository(database) as repository:
            assert repository.load_runnable_jobs(recover_interrupted=True) == []
            job = repository.get_job_model("interrupted")
            assert job is not None and job.status is JobStatus.FAILED
            assert job.execution_metadata.return_to_queue_count == 2
            queue = JobQueue(repository=repository)
            assert queue.claim_next_job() is None
            assert queue.get_next_job() is None
