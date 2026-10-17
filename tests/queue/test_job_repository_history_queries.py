"""History list queries: newest-first results, bounded work, and the created_at index."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from src.pipeline.cli_njr_builder import build_cli_njr
from src.queue.job_model import Job, JobStatus
from src.queue.job_repository import CREATED_AT_INDEX, JobRepository


def _job(job_id: str) -> Job:
    record = build_cli_njr(
        prompt=f"prompt {job_id}",
        batch_size=1,
        run_name=job_id,
        config={
            "txt2img": {
                "model": "m.safetensors",
                "steps": 4,
                "cfg_scale": 5.0,
                "width": 64,
                "height": 64,
            }
        },
    )
    record = replace(record, job_id=job_id)
    job = Job(job_id=job_id, snapshot={"normalized_job": record.to_dict()})
    job._normalized_record = record  # type: ignore[attr-defined]
    return job


def _seed(repository: JobRepository, rows: list[tuple[str, str, str]]) -> None:
    """Insert ``(job_id, created_at, status)`` rows with chosen creation times and statuses."""

    for job_id, created_at, status in rows:
        repository.record_job_submission(_job(job_id))
        with repository.transaction() as connection:
            connection.execute(
                "UPDATE jobs SET created_at = ?, status = ? WHERE job_id = ?",
                (created_at, status, job_id),
            )


ROWS = [
    ("j1", "2026-10-01T10:00:00", "completed"),
    ("j2", "2026-10-02T10:00:00", "failed"),
    ("j3", "2026-10-03T10:00:00", "completed"),
    ("j4", "2026-10-04T10:00:00", "queued"),
    ("j5", "2026-10-05T10:00:00", "completed"),
    ("j6", "2026-10-06T10:00:00", "cancelled"),
]


def _index_names(repository: JobRepository) -> set[str]:
    with repository.transaction() as connection:
        return {
            row["name"]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='index'")
        }


def test_new_repositories_have_the_created_at_index(tmp_path: Path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite3")

    assert CREATED_AT_INDEX in _index_names(repository)


def test_an_existing_repository_without_the_index_gets_it_once_and_keeps_its_rows(
    tmp_path: Path,
) -> None:
    path = tmp_path / "jobs.sqlite3"
    first = JobRepository(path)
    _seed(first, ROWS)
    with first.transaction() as connection:
        connection.execute(f"DROP INDEX {CREATED_AT_INDEX}")
    first.close()

    reopened = JobRepository(path)
    assert CREATED_AT_INDEX in _index_names(reopened)
    assert [entry.job_id for entry in reopened.list_jobs(limit=100)] == [
        "j6",
        "j5",
        "j4",
        "j3",
        "j2",
        "j1",
    ]
    reopened.close()

    again = JobRepository(path)  # idempotent: nothing to build, nothing lost
    assert CREATED_AT_INDEX in _index_names(again)
    assert again.count() == len(ROWS)


def test_newest_jobs_are_read_through_the_index_not_a_sorted_scan(tmp_path: Path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    _seed(repository, ROWS)

    with repository.transaction() as connection:
        plan = " | ".join(
            row["detail"]
            for row in connection.execute(
                "EXPLAIN QUERY PLAN SELECT job_id FROM jobs ORDER BY created_at DESC LIMIT 5"
            )
        )

    assert CREATED_AT_INDEX in plan
    assert "TEMP B-TREE" not in plan


def test_list_jobs_is_newest_first_with_limit_offset_and_status(tmp_path: Path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    _seed(repository, ROWS)

    assert [e.job_id for e in repository.list_jobs(limit=3)] == ["j6", "j5", "j4"]
    assert [e.job_id for e in repository.list_jobs(limit=2, offset=2)] == ["j4", "j3"]
    assert [e.job_id for e in repository.list_jobs(status=JobStatus.COMPLETED, limit=10)] == [
        "j5",
        "j3",
        "j1",
    ]
    assert [
        e.job_id for e in repository.list_jobs(status=JobStatus.COMPLETED, limit=1, offset=1)
    ] == ["j3"]
    assert repository.list_jobs(limit=0) == []
    assert repository.list_jobs(limit=5, offset=100) == []


def test_list_recent_jobs_filters_by_status_newest_first(tmp_path: Path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    _seed(repository, ROWS)

    terminal = {JobStatus.COMPLETED, JobStatus.FAILED}
    assert [e.job_id for e in repository.list_recent_jobs(statuses=terminal, limit=4)] == [
        "j5",
        "j3",
        "j2",
        "j1",
    ]
    assert [e.job_id for e in repository.list_recent_jobs(statuses=terminal, limit=2)] == [
        "j5",
        "j3",
    ]
    assert [e.job_id for e in repository.list_recent_jobs(limit=2)] == ["j6", "j5"]


def test_history_entries_still_carry_the_full_snapshot_and_fields(tmp_path: Path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    _seed(repository, ROWS[:1])

    (entry,) = repository.list_jobs(limit=1)

    assert entry.job_id == "j1"
    assert entry.status == JobStatus.COMPLETED
    assert entry.snapshot["normalized_job"]["job_id"] == "j1"
