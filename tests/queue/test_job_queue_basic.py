from __future__ import annotations

import threading

from src.queue.job_model import Job, JobPriority, JobStatus
from src.queue.job_queue import JobQueue


def test_job_queue_respects_priority_and_fifo():
    queue = JobQueue()
    queue.submit(Job("low-1", priority=JobPriority.LOW))
    queue.submit(Job("high-1", priority=JobPriority.HIGH))
    queue.submit(Job("norm-1", priority=JobPriority.NORMAL))
    queue.submit(Job("high-2", priority=JobPriority.HIGH))

    order = [queue.get_next_job().job_id for _ in range(4)]
    assert order[:2] == ["high-1", "high-2"]
    assert order[2:] == ["norm-1", "low-1"]


def test_job_queue_status_transitions():
    queue = JobQueue()
    job = Job("j1")
    queue.submit(job)
    next_job = queue.get_next_job()
    assert next_job.job_id == "j1"
    queue.mark_running("j1")
    assert job.status == JobStatus.RUNNING
    queue.mark_completed("j1", result={"ok": True})
    assert job.status == JobStatus.COMPLETED
    assert job.result == {"ok": True}
    queue.mark_failed("j1", "error")  # even completed, should update status
    assert job.status == JobStatus.FAILED
    assert job.error_message == "error"


def test_state_listener_notified_on_changes() -> None:
    queue = JobQueue()
    events: list[str] = []
    queue.register_state_listener(lambda: events.append("updated"))

    queue.submit(Job("listener-job"))
    assert events


def test_restore_jobs_repopulate_queue() -> None:
    queue = JobQueue()
    job = Job("restored-job")
    queue.restore_jobs([job])

    restored = queue.get_job("restored-job")
    assert restored is job


def test_remove_listener_can_reenter_queue_without_deadlock() -> None:
    queue = JobQueue()
    queue.submit(Job("j1"))
    queue.submit(Job("j2"))
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
    queue.submit(Job("j1"))
    queue.submit(Job("j2"))
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
    job = Job("running-job")
    queue.submit(job)
    queue.mark_running(job.job_id)

    removed = queue.remove(job.job_id)

    assert removed is None
    assert queue.get_job(job.job_id) is job
    assert job.status == JobStatus.RUNNING


def test_list_active_jobs_ordered_returns_running_then_queue_order() -> None:
    queue = JobQueue()
    queued_first = Job("queued-1", priority=JobPriority.NORMAL)
    queued_second = Job("queued-2", priority=JobPriority.NORMAL)
    queue.submit(queued_first)
    queue.submit(queued_second)
    running = queue.get_next_job()
    queue.mark_running(running.job_id)

    ordered = queue.list_active_jobs_ordered()

    assert [job.job_id for job in ordered] == ["queued-1", "queued-2"]
