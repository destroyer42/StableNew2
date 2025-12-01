from __future__ import annotations

from typing import Any, Callable, Tuple

import pytest

from src.controller.app_controller import AppController
from src.controller.job_service import JobService
from src.gui.app_state_v2 import AppStateV2, PackJobEntry


class FakeJobService:
    """Lightweight stand-in for JobService used in controller integration tests."""

    EVENT_QUEUE_UPDATED = JobService.EVENT_QUEUE_UPDATED
    EVENT_QUEUE_STATUS = JobService.EVENT_QUEUE_STATUS

    def __init__(self) -> None:
        self._listeners: dict[str, list[Callable[..., Any]]] = {}
        self.enqueue_calls = 0
        self.run_now_calls = 0
        self.pause_calls = 0
        self.resume_calls = 0
        self.cancel_calls = 0
        self.last_job = None

    def register_callback(self, event: str, callback: callable) -> None:
        self._listeners.setdefault(event, []).append(callback)

    def enqueue(self, job) -> None:
        self.enqueue_calls += 1
        self.last_job = job

    def run_now(self, job) -> None:
        self.run_now_calls += 1
        self.last_job = job

    def pause(self) -> None:
        self.pause_calls += 1

    def resume(self) -> None:
        self.resume_calls += 1

    def cancel_current(self) -> None:
        self.cancel_calls += 1

    def emit(self, event: str, *args) -> None:
        for callback in self._listeners.get(event, []):
            callback(*args)


def _build_controller() -> Tuple[AppController, FakeJobService]:
    fake_service = FakeJobService()
    controller = AppController(None, threaded=False, job_service=fake_service)
    controller.app_state = AppStateV2()
    return controller, fake_service


def _attach_dummy_draft(controller: AppController) -> None:
    controller.app_state.clear_job_draft()
    entry = PackJobEntry(
        pack_id="pack-alpha",
        pack_name="Pack Alpha",
        config_snapshot={"randomization_enabled": False},
    )
    controller.app_state.add_packs_to_job_draft([entry])


def test_on_add_job_to_queue_enqueues_and_updates_state() -> None:
    controller, fake_service = _build_controller()
    _attach_dummy_draft(controller)

    controller.on_add_job_to_queue()
    assert fake_service.enqueue_calls == 1
    assert fake_service.last_job is not None

    fake_service.emit(FakeJobService.EVENT_QUEUE_UPDATED, ["job-summary"])
    assert controller.app_state.queue_items == ["job-summary"]


def test_on_run_job_now_sets_running_status() -> None:
    controller, fake_service = _build_controller()
    _attach_dummy_draft(controller)

    controller.on_run_job_now()
    assert fake_service.run_now_calls == 1

    fake_service.emit(FakeJobService.EVENT_QUEUE_STATUS, "running")
    assert controller.app_state.queue_status == "running"


def test_queue_controls_delegate_and_update_ui_state() -> None:
    controller, fake_service = _build_controller()

    controller.on_pause_queue()
    controller.on_resume_queue()
    controller.on_cancel_current_job()

    assert fake_service.pause_calls == 1
    assert fake_service.resume_calls == 1
    assert fake_service.cancel_calls == 1

    fake_service.emit(FakeJobService.EVENT_QUEUE_STATUS, "paused")
    assert controller.app_state.queue_status == "paused"

    fake_service.emit(FakeJobService.EVENT_QUEUE_STATUS, "idle")
    assert controller.app_state.queue_status == "idle"
