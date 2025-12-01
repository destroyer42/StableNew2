from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from src.controller.app_controller import AppController
from src.controller.job_service import JobService
from src.gui.app_state_v2 import AppStateV2
from src.queue.job_history_store import JobHistoryEntry, JobStatus


class FakeHistoryStore:
    def __init__(self, entries: list[JobHistoryEntry]) -> None:
        self._entries = list(entries)

    def list_jobs(self, *args: Any, **kwargs: Any) -> list[JobHistoryEntry]:
        return list(self._entries)


class FakeJobService:
    EVENT_JOB_FINISHED = JobService.EVENT_JOB_FINISHED
    EVENT_JOB_FAILED = JobService.EVENT_JOB_FAILED

    def __init__(self, history_store: FakeHistoryStore) -> None:
        self.history_store = history_store
        self._listeners: dict[str, list[callable]] = {}

    def register_callback(self, event: str, callback: callable) -> None:
        self._listeners.setdefault(event, []).append(callback)

    def emit(self, event: str, *args: Any) -> None:
        for callback in self._listeners.get(event, []):
            callback(*args)


def _build_entry(job_id: str) -> JobHistoryEntry:
    now = datetime.utcnow()
    later = now
    return JobHistoryEntry(
        job_id=job_id,
        created_at=now,
        status=JobStatus.COMPLETED,
        payload_summary="Example pack",
        started_at=now,
        completed_at=later,
    )


def _make_controller(entries: list[JobHistoryEntry]) -> tuple[AppController, FakeJobService]:
    store = FakeHistoryStore(entries)
    service = FakeJobService(store)
    controller = AppController(None, threaded=False, job_service=service)
    controller.app_state = AppStateV2()
    return controller, service


def test_history_updates_on_job_completion() -> None:
    entry = _build_entry("history-1")
    controller, service = _make_controller([entry])

    service.emit(FakeJobService.EVENT_JOB_FINISHED, None)
    assert controller.app_state.history_items
    assert controller.app_state.history_items[0].job_id == "history-1"


def test_manual_refresh_reloads_history() -> None:
    entry = _build_entry("manual-refresh")
    controller, _ = _make_controller([entry])
    controller.app_state.set_history_items([])

    controller.refresh_job_history()
    assert controller.app_state.history_items[0].job_id == "manual-refresh"
