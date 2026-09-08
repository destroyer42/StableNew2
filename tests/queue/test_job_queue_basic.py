from __future__ import annotations

import threading

from src.queue.job_model import JobPriority, JobStatus
from src.queue.job_queue import JobQueue
from tests.helpers.njr_factory import make_queue_job


def test_job_queue_respects_priority_and_fifo():
    queue = JobQueue()
    queue.submit(make_queue_job("low-1", priority=JobPriority.LOW))
    queue.submit(make_queue_job("high-1", priority=JobPriority.HIGH))
    queue.submit(make_queue_job("norm-1", priority=JobPriority.NORMAL))
    queue.submit(make_queue_job("high-2", priority=JobPriority.HIGH))

    order = [queue.get_next_job().job_id for _ in range(4)]
    assert order[:2] == ["high-1", "high-2"]
    assert order[2:] == ["norm-1", "low-1"]


def test_job_queue_status_transitions():
    queue = JobQueue()
    job = make_queue_job("j1")
    queue.submit(job)
    next_job = queue.get_next_job()
    assert next_job.job_id == "j1"
    queue.mark_running("j1")
    assert job.status == JobStatus.RUNNING
    queue.mark_completed("j1", result={"ok": True})
    assert job.status == JobStatus.COMPLETED
    assert job.result == {"ok": True}
    queue.mark_failed("j1", "error")
    assert job.status == JobStatus.COMPLETED


def test_state_listener_notified_on_changes() -> None:
    queue = JobQueue()
    events: list[str] = []
    queue.register_state_listener(lambda: events.append("updated"))

    queue.submit(make_queue_job("listener-job"))
    assert events


def test_state_listener_notifications_can_be_coalesced() -> None:
    queue = JobQueue()
    events: list[str] = []
    queue.register_state_listener(lambda: events.append("updated"))

    with queue.coalesce_state_notifications():
        queue.submit(make_queue_job("listener-job-1"))
        queue.submit(make_queue_job("listener-job-2"))

    assert events == ["updated"]


def test_restore_jobs_repopulate_queue() -> None:
    queue = JobQueue()
    job = make_queue_job("restored-job")
    queue.restore_jobs([job])

    restored = queue.get_job("restored-job")
    assert restored is job


def test_queue_pause_resume_blocks_and_restores_dequeue() -> None:
    queue = JobQueue()
    queue.submit(make_queue_job("j1"))

    queue.pause()
    assert queue.is_paused() is True
    assert queue.get_next_job() is None

    queue.resume()
    assert queue.is_paused() is False
    assert queue.get_next_job().job_id == "j1"


def test_remove_listener_can_reenter_queue_without_deadlock() -> None:
    queue = JobQueue()
    queue.submit(make_queue_job("j1"))
    queue.submit(make_queue_job("j2"))
    completed = threading.Event()

    def _listener() -> None:
        queue.list_jobs()
        completed.set()

    queue.register_state_listener(_listener)
    worker = threading.Thread(target=lambda: queue.remove("j1"), daemon=True)
    worker.start()
    worker.join(timeout=1.0)

    assert not worker.is_alive()
    assert completed.is_set()


def test_clear_listener_can_reenter_queue_without_deadlock() -> None:
    queue = JobQueue()
    queue.submit(make_queue_job("j1"))
    queue.submit(make_queue_job("j2"))
    completed = threading.Event()

    def _listener() -> None:
        queue.list_jobs()
        completed.set()

    queue.register_state_listener(_listener)
    worker = threading.Thread(target=queue.clear, daemon=True)
    worker.start()
    worker.join(timeout=1.0)

    assert not worker.is_alive()
    assert completed.is_set()


def test_remove_refuses_running_job() -> None:
    queue = JobQueue()
    job = make_queue_job("running-job")
    queue.submit(job)
    queue.mark_running(job.job_id)

    removed = queue.remove(job.job_id)

    assert removed is None
    assert queue.get_job(job.job_id) is job
    assert job.status == JobStatus.RUNNING


def test_list_active_jobs_ordered_returns_running_then_queue_order() -> None:
    queue = JobQueue()
    queued_first = make_queue_job("queued-1", priority=JobPriority.NORMAL)
    queued_second = make_queue_job("queued-2", priority=JobPriority.NORMAL)
    queue.submit(queued_first)
    queue.submit(queued_second)
    running = queue.get_next_job()
    queue.mark_running(running.job_id)

    ordered = queue.list_active_jobs_ordered()

    assert [job.job_id for job in ordered] == ["queued-1", "queued-2"]


def test_cancel_running_job_return_to_queue_requeues_at_back() -> None:
    queue = JobQueue()
    first = make_queue_job("first")
    second = make_queue_job("second")
    queue.submit(first)
    queue.submit(second)

    running = queue.get_next_job()
    queue.mark_running(running.job_id)

    returned = queue.cancel_running_job(return_to_queue=True)

    assert returned is running
    assert running.status == JobStatus.QUEUED
    ordered = queue.list_active_jobs_ordered()
    assert [job.job_id for job in ordered] == ["second", "first"]
    assert running.execution_metadata.return_to_queue_count == 1
