"""LAUNCH-UPDATE-1: the queue's in-memory update hold (drain before an update restart).

Real ``JobQueue`` / SQLite ``JobRepository``. The hold stops every claim without reordering or mutating a job and is
never persisted, so after a restart the queue comes back under its normal startup policy.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.queue.job_model import JobPriority, JobStatus
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from tests.queue.test_webui_outage_containment_171 import comfy, image, svd, unresolved


@pytest.fixture
def repository(tmp_path: Path):
    repo = JobRepository(tmp_path / "queue.db")
    yield repo
    try:
        repo.close()
    except Exception:
        pass


def queued_ids(queue: JobQueue) -> list[str]:
    return [
        job.job_id for job in queue.list_active_jobs_ordered() if job.status is JobStatus.QUEUED
    ]


def test_update_hold_stops_every_claim_without_reordering(repository):
    queue = JobQueue(repository=repository)
    jobs = [
        image("a"),
        svd("b"),
        comfy("c"),
        unresolved("d"),
        image("e", priority=JobPriority.HIGH),
    ]
    for job in jobs:
        queue.submit(job)
    order = queued_ids(queue)

    assert queue.hold_dispatch_for_update(reason="live-update") is True
    assert queue.hold_dispatch_for_update(reason="second") is False  # the first hold is kept

    assert queue.is_update_held()
    assert queue.update_hold_info() == {"reason": "live-update"}
    assert queue.claim_next_job() is None
    assert queue.get_next_job() is None
    assert queue.peek_next_dispatch_candidate() is None
    assert all(queue.mark_running(job.job_id) is None for job in jobs)
    assert all(queue.is_job_held(job.job_id) for job in jobs)
    assert not any(queue.is_job_held_by_webui(job.job_id) for job in jobs)
    assert queued_ids(queue) == order == ["e", "a", "b", "c", "d"]
    assert {job.job_id: repository.get_job(job.job_id).status for job in jobs} == dict.fromkeys(
        (job.job_id for job in jobs), JobStatus.QUEUED
    )
    assert queue.dispatch_summary()["held_update"] == 5
    assert not queue.is_paused()


def test_release_restores_priority_then_fifo_order(repository):
    queue = JobQueue(repository=repository)
    for job in (image("a"), image("b", priority=JobPriority.HIGH), svd("c")):
        queue.submit(job)
    queue.hold_dispatch_for_update(reason="live-update")

    assert queue.release_update_hold() is True
    assert queue.release_update_hold() is False
    claimed = []
    while (job := queue.claim_next_job()) is not None:
        claimed.append(job.job_id)
    assert claimed == ["b", "a", "c"]


def test_update_hold_is_never_persisted(tmp_path):
    path = tmp_path / "restart.db"
    first = JobRepository(path)
    queue = JobQueue(repository=first)
    queue.submit(image("a"))
    queue.hold_dispatch_for_update(reason="live-update")
    assert first.get_setting("queue_paused", False) is False
    first.close()

    second = JobRepository(path)
    try:
        restored = JobQueue(repository=second)
        assert not restored.is_update_held() and not restored.is_paused()
        assert queued_ids(restored) == ["a"]
        assert restored.claim_next_job().job_id == "a"
    finally:
        second.close()
