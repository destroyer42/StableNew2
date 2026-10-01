from __future__ import annotations

from typing import Any

from src.controller.app_controller import AppController
from src.controller.job_service import JobService
from src.queue.job_queue import JobQueue
from tests.helpers.njr_factory import make_queue_job


class FakeJobService:
    """Minimal JobService stand-in over a real JobQueue/JobRepository (history projection)."""

    EVENT_JOB_FINISHED = JobService.EVENT_JOB_FINISHED
    EVENT_JOB_FAILED = JobService.EVENT_JOB_FAILED

    def __init__(self, queue: JobQueue) -> None:
        self.queue = queue
        self.history_store = queue.repository
        self._listeners: dict[str, list[callable]] = {}

    def register_callback(self, event: str, callback: callable) -> None:
        self._listeners.setdefault(event, []).append(callback)

    def emit(self, event: str, *args: Any) -> None:
        for callback in self._listeners.get(event, []):
            callback(*args)


def _complete_job(queue: JobQueue, job_id: str) -> None:
    """Drive a queued NJR-backed job to COMPLETED so the repository projects it as history."""
    queue.submit(make_queue_job(job_id))
    queue.mark_running(job_id)
    queue.mark_completed(job_id, {"variants": []})


def _make_controller() -> tuple[AppController, FakeJobService]:
    service = FakeJobService(JobQueue())
    # Use the controller-owned AppState: the projection sink is bound to it at construction.
    controller = AppController(None, threaded=False, job_service=service)
    return controller, service


def test_history_updates_on_job_completion() -> None:
    controller, service = _make_controller()
    _complete_job(service.queue, "history-1")

    service.emit(FakeJobService.EVENT_JOB_FINISHED, None)
    assert controller.app_state.history_items
    assert controller.app_state.history_items[0].job_id == "history-1"


def test_manual_refresh_reloads_history() -> None:
    controller, service = _make_controller()
    _complete_job(service.queue, "manual-refresh")
    controller.app_state.set_history_items([])

    controller.refresh_job_history()
    assert controller.app_state.history_items[0].job_id == "manual-refresh"
