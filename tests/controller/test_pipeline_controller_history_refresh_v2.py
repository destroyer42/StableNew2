from __future__ import annotations

from datetime import datetime

from src.gui.app_state_v2 import AppStateV2
from src.controller.pipeline_controller import PipelineController
from src.queue.job_history_store import JobHistoryEntry
from src.queue.job_model import JobStatus


class _FakeHistoryStore:
    def __init__(self) -> None:
        self.called = False

    def list_jobs(self, *, limit: int = 20, status=None, offset=0):
        self.called = True
        return [
            JobHistoryEntry(
                job_id="job-alpha",
                created_at=datetime.utcnow(),
                status=JobStatus.COMPLETED,
            )
        ]


class _FakeJobService:
    def __init__(self) -> None:
        self.history_store = _FakeHistoryStore()


def _make_controller() -> PipelineController:
    ctrl = PipelineController.__new__(PipelineController)
    ctrl._app_state = AppStateV2()
    ctrl._job_service = _FakeJobService()
    return ctrl


def test_refresh_app_state_history_populates_from_store() -> None:
    ctrl = _make_controller()
    ctrl._refresh_app_state_history()
    assert ctrl._app_state.history_items
    assert ctrl._job_service.history_store.called


def test_on_history_entry_updated_triggers_refresh(monkeypatch) -> None:
    ctrl = _make_controller()
    called: list[bool] = []

    def fake_refresh() -> None:
        called.append(True)

    ctrl._refresh_app_state_history = fake_refresh  # type: ignore[attr-defined]
    entry = JobHistoryEntry(
        job_id="job-beta",
        created_at=datetime.utcnow(),
        status=JobStatus.COMPLETED,
    )
    ctrl._on_history_entry_updated(entry)
    assert called
