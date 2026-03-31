from __future__ import annotations

from datetime import datetime

from src.controller.pipeline_controller import PipelineController
from src.gui.app_state_v2 import AppStateV2
from src.queue.job_history_store import JobHistoryEntry
from src.queue.job_model import Job, JobStatus
from src.utils.snapshot_builder_v2 import build_job_snapshot

from tests.helpers.job_helpers import make_test_njr


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
    ctrl._app_state_queue_updates_managed_externally = False
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


def test_on_history_entry_updated_ignores_non_terminal_statuses() -> None:
    ctrl = _make_controller()
    called: list[bool] = []

    def fake_refresh() -> None:
        called.append(True)

    ctrl._refresh_app_state_history = fake_refresh  # type: ignore[attr-defined]
    entry = JobHistoryEntry(
        job_id="job-gamma",
        created_at=datetime.utcnow(),
        status=JobStatus.QUEUED,
    )
    ctrl._on_history_entry_updated(entry)
    assert called == []


def test_on_history_entry_updated_skips_when_external_owner_manages_app_state() -> None:
    ctrl = _make_controller()
    ctrl._app_state_queue_updates_managed_externally = True
    called: list[bool] = []

    def fake_refresh() -> None:
        called.append(True)

    ctrl._refresh_app_state_history = fake_refresh  # type: ignore[attr-defined]
    entry = JobHistoryEntry(
        job_id="job-delta",
        created_at=datetime.utcnow(),
        status=JobStatus.COMPLETED,
    )

    ctrl._on_history_entry_updated(entry)

    assert called == []


def test_refresh_app_state_queue_recovers_njr_from_snapshot() -> None:
    ctrl = _make_controller()
    job = Job(job_id="job-queued")
    job.status = JobStatus.RUNNING
    job.snapshot = build_job_snapshot(job, make_test_njr(job_id=job.job_id))
    ctrl._list_service_jobs = lambda: [job]  # type: ignore[attr-defined]

    ctrl._refresh_app_state_queue()

    assert ctrl._app_state.queue_jobs
    assert ctrl._app_state.queue_jobs[0].job_id == "job-queued"
    assert ctrl._app_state.queue_jobs[0].status == "RUNNING"


def test_on_queue_status_changed_skips_when_external_owner_manages_app_state() -> None:
    ctrl = _make_controller()
    ctrl._app_state_queue_updates_managed_externally = True
    statuses: list[str] = []
    ctrl._app_state.set_queue_status = lambda status: statuses.append(status)  # type: ignore[method-assign]

    ctrl._on_queue_status_changed("running")

    assert statuses == []


def test_on_job_started_skips_when_external_owner_manages_app_state() -> None:
    ctrl = _make_controller()
    ctrl._app_state_queue_updates_managed_externally = True
    jobs: list[str] = []
    ctrl._set_running_job = lambda job: jobs.append(getattr(job, "job_id", "none"))  # type: ignore[method-assign]

    ctrl._on_job_started(Job(job_id="job-running"))

    assert jobs == []
