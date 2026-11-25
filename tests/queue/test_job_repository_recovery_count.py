"""PR-GUI-STALL-ATTRIBUTION: counting interrupted-restart jobs must not hold the shared repository lock.

``count_jobs_with_last_control_action`` has to read ``execution_metadata`` of every row. That column sits after the
~90 KB ``njr_snapshot`` of each row, so SQLite walks every row's overflow chain: the whole multi-gigabyte file is read.
It used to do that under ``JobRepository._lock``, which every queue transition and progress commit also needs, so one
Operator Readiness refresh stalled the job worker as well as the Tk thread. It now reads on its own read-only
connection (a WAL reader sees a consistent snapshot and never blocks the writer), without taking the shared lock.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from src.queue.job_model import JobStatus
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from tests.queue.test_job_repository_sqlite import _job

ACTION = "restart_interrupted_action_required"


def _repository_with_interrupted_jobs(path: Path, interrupted: int, ordinary: int) -> None:
    repository = JobRepository(path)
    queue = JobQueue(repository=repository)
    for index in range(interrupted):
        queue.submit(_job(f"interrupted-{index}"))
        queue.mark_running(f"interrupted-{index}")
    for index in range(ordinary):
        queue.submit(_job(f"ordinary-{index}"))
    repository.close()


def test_counts_only_jobs_recovered_after_an_interrupted_restart(tmp_path: Path) -> None:
    path = tmp_path / "jobs.sqlite3"
    _repository_with_interrupted_jobs(path, interrupted=3, ordinary=2)
    repository = JobRepository(path)
    JobQueue(repository=repository)  # restart: the running jobs are recovered as action-required
    try:
        assert repository.count_jobs_with_last_control_action(ACTION) == 3
        assert repository.count_jobs_with_last_control_action("something_else") == 0
        assert repository.count() == 5
    finally:
        repository.close()


def test_the_count_does_not_wait_for_the_repository_lock(tmp_path: Path) -> None:
    path = tmp_path / "jobs.sqlite3"
    _repository_with_interrupted_jobs(path, interrupted=2, ordinary=0)
    repository = JobRepository(path)
    JobQueue(repository=repository)
    result: list[int] = []
    try:
        with repository._lock:  # noqa: SLF001 - a worker is mid-commit: the shared lock is taken
            reader = threading.Thread(
                target=lambda: result.append(repository.count_jobs_with_last_control_action(ACTION))
            )
            reader.start()
            reader.join(5.0)
            assert not reader.is_alive(), "the count blocked on the shared repository lock"
        assert result == [2]
    finally:
        repository.close()


def test_the_count_sees_the_committed_state_while_a_writer_is_open(tmp_path: Path) -> None:
    path = tmp_path / "jobs.sqlite3"
    _repository_with_interrupted_jobs(path, interrupted=1, ordinary=0)
    repository = JobRepository(path)
    queue = JobQueue(repository=repository)
    try:
        queue.submit(_job("new-work"))
        # A new transaction is open on the shared connection but not committed.
        repository._connection.execute("BEGIN IMMEDIATE")  # noqa: SLF001
        repository._connection.execute(  # noqa: SLF001
            "UPDATE jobs SET execution_metadata = ? WHERE job_id = 'new-work'",
            ('{"last_control_action": "restart_interrupted_action_required"}',),
        )
        try:
            assert (
                repository.count_jobs_with_last_control_action(ACTION) == 1
            )  # the uncommitted row is not counted
        finally:
            repository._connection.rollback()  # noqa: SLF001
    finally:
        repository.close()


def test_a_corrupt_metadata_row_is_not_counted_and_does_not_break_the_count(tmp_path: Path) -> None:
    path = tmp_path / "jobs.sqlite3"
    _repository_with_interrupted_jobs(path, interrupted=1, ordinary=1)
    repository = JobRepository(path)
    JobQueue(repository=repository)
    try:
        with repository.transaction() as connection:
            connection.execute(
                "UPDATE jobs SET execution_metadata = '{not json' WHERE job_id = 'ordinary-0'"
            )
        assert repository.count_jobs_with_last_control_action(ACTION) == 1
    finally:
        repository.close()


def test_an_in_memory_repository_still_counts() -> None:
    repository = JobRepository(":memory:")
    queue = JobQueue(repository=repository)
    queue.submit(_job("only"))
    queue.mark_running("only")
    try:
        assert repository.count_jobs_with_last_control_action(ACTION) == 0
        assert queue.get_job("only").status == JobStatus.RUNNING  # type: ignore[union-attr]
    finally:
        repository.close()


def test_the_reader_opens_the_database_read_only(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "jobs.sqlite3"
    _repository_with_interrupted_jobs(path, interrupted=1, ordinary=0)
    repository = JobRepository(path)
    JobQueue(repository=repository)
    uris: list[str] = []
    real_connect = sqlite3.connect

    def spying_connect(database, *args, **kwargs):
        uris.append(str(database))
        return real_connect(database, *args, **kwargs)

    monkeypatch.setattr("src.queue.job_repository.sqlite3.connect", spying_connect)
    try:
        repository.count_jobs_with_last_control_action(ACTION)
        assert any("mode=ro" in uri for uri in uris)
    finally:
        repository.close()
