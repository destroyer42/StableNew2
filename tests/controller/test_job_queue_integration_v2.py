from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.controller.app_controller import AppController
from src.controller.job_service import JobService
from src.gui.app_state_v2 import AppStateV2, PackJobEntry
from src.pipeline.job_models_v2 import JobStatusV2, NormalizedJobRecord
from src.queue.job_model import Job, JobStatus
from src.utils.snapshot_builder_v2 import build_job_snapshot


class FakeJobService:
    """Lightweight stand-in for JobService used in controller integration tests."""

    EVENT_QUEUE_UPDATED = JobService.EVENT_QUEUE_UPDATED
    EVENT_QUEUE_STATUS = JobService.EVENT_QUEUE_STATUS

    def __init__(self) -> None:
        self._listeners: dict[str, list[Callable[..., Any]]] = {}
        self._state_listeners: list[Callable[[], None]] = []
        self.enqueue_calls = 0
        self.run_now_calls = 0
        self.pause_calls = 0
        self.resume_calls = 0
        self.cancel_calls = 0
        self.cancel_return_calls = 0
        self.last_job = None
        self._jobs: list[Job] = []
        self.queue = self

    def register_callback(self, event: str, callback: callable) -> None:
        self._listeners.setdefault(event, []).append(callback)

    def enqueue(self, job) -> None:
        self.enqueue_calls += 1
        self.last_job = job
        for listener in self._state_listeners:
            listener()

    def run_now(self, job) -> None:
        self.run_now_calls += 1
        self.last_job = job
        for listener in self._state_listeners:
            listener()

    def register_state_listener(self, callback: Callable[[], None]) -> None:
        self._state_listeners.append(callback)

    def pause(self) -> None:
        self.pause_calls += 1

    def resume(self) -> None:
        self.resume_calls += 1

    def cancel_current(self, *, return_to_queue: bool = False) -> None:
        self.cancel_calls += 1
        if return_to_queue:
            self.cancel_return_calls += 1

    def emit(self, event: str, *args) -> None:
        for callback in self._listeners.get(event, []):
            callback(*args)

    def list_jobs(self) -> list[Job]:
        return list(self._jobs)

    def set_jobs(self, jobs: list[Job]) -> None:
        self._jobs = list(jobs)
        for listener in self._state_listeners:
            listener()


def _build_controller() -> tuple[AppController, FakeJobService]:
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


def _make_njr(job_id: str = "job-1") -> NormalizedJobRecord:
    return NormalizedJobRecord(
        job_id=job_id,
        config={"prompt": "portrait"},
        path_output_dir="output",
        filename_template="{seed}",
        seed=123,
        variant_index=0,
        variant_total=1,
        batch_index=0,
        batch_total=1,
        created_ts=1.0,
        prompt_pack_id="pack-1",
        prompt_pack_name="Pack 1",
        prompt_pack_row_index=0,
        positive_prompt="portrait",
        negative_prompt="",
        steps=20,
        cfg_scale=7.0,
        width=512,
        height=512,
        sampler_name="Euler a",
        scheduler="ddim",
        clip_skip=0,
        base_model="sdxl",
        stage_chain=[],
        loop_type="pipeline",
        loop_count=1,
        images_per_prompt=1,
        variant_mode="standard",
        run_mode="QUEUE",
        queue_source="ADD_TO_QUEUE",
        randomization_enabled=False,
        config_variant_label="base",
        config_variant_index=0,
        status=JobStatusV2.QUEUED,
    )


def test_on_add_job_to_queue_enqueues_and_updates_state() -> None:
    controller, fake_service = _build_controller()
    _attach_dummy_draft(controller)

    controller.on_add_job_to_queue()
    assert fake_service.enqueue_calls == 1
    assert fake_service.last_job is not None

    job = Job(job_id="job-alpha")
    job.status = JobStatus.QUEUED
    fake_service.set_jobs([job])
    fake_service.emit(FakeJobService.EVENT_QUEUE_UPDATED, ["job-summary"])
    assert controller.app_state.queue_jobs
    assert controller.app_state.queue_jobs[0].job_id == "job-alpha"


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


def test_queue_status_change_requests_queue_refresh() -> None:
    controller, _fake_service = _build_controller()
    refresh_calls: list[str] = []
    controller._run_in_gui_thread = lambda fn: fn()
    controller._request_queue_state_refresh = lambda: refresh_calls.append("refresh")

    controller._on_queue_status_changed("running")

    assert controller.app_state.queue_status == "running"
    assert refresh_calls == ["refresh"]


def test_cancel_and_return_uses_job_service_contract() -> None:
    controller, fake_service = _build_controller()

    controller.on_cancel_job_and_return_v2()

    assert fake_service.cancel_calls == 1
    assert fake_service.cancel_return_calls == 1


def test_running_job_summary_uses_live_job_status() -> None:
    controller, _fake_service = _build_controller()
    job = Job(job_id="job-running")
    job.status = JobStatus.RUNNING
    job._normalized_record = _make_njr(job.job_id)  # type: ignore[attr-defined]

    controller._set_running_job(job)

    assert controller.app_state.running_job is not None
    assert controller.app_state.running_job.status == "RUNNING"


def test_running_job_summary_recovers_njr_from_snapshot() -> None:
    controller, _fake_service = _build_controller()
    job = Job(job_id="job-running")
    job.status = JobStatus.RUNNING
    job.snapshot = build_job_snapshot(job, _make_njr(job.job_id))

    controller._set_running_job(job)

    assert controller.app_state.running_job is not None
    assert controller.app_state.running_job.job_id == "job-running"
    assert controller.app_state.running_job.status == "RUNNING"


def test_queue_refresh_uses_live_status_for_njr_jobs() -> None:
    controller, fake_service = _build_controller()
    job = Job(job_id="job-running")
    job.status = JobStatus.RUNNING
    job._normalized_record = _make_njr(job.job_id)  # type: ignore[attr-defined]
    fake_service.set_jobs([job])

    controller._refresh_app_state_queue()

    assert controller.app_state.queue_jobs
    assert controller.app_state.queue_jobs[0].status == "RUNNING"


def test_queue_refresh_recovers_njr_from_snapshot() -> None:
    controller, fake_service = _build_controller()
    job = Job(job_id="job-running")
    job.status = JobStatus.RUNNING
    job.snapshot = build_job_snapshot(job, _make_njr(job.job_id))
    fake_service.set_jobs([job])

    controller._refresh_app_state_queue()

    assert controller.app_state.queue_jobs
    assert controller.app_state.queue_jobs[0].job_id == "job-running"
    assert controller.app_state.queue_jobs[0].status == "RUNNING"


def test_job_started_requests_queue_refresh() -> None:
    controller, _fake_service = _build_controller()
    refresh_calls: list[str] = []
    controller._run_in_gui_thread = lambda fn: fn()
    controller._request_queue_state_refresh = lambda: refresh_calls.append("refresh")

    controller._on_job_started(Job(job_id="job-running"))

    assert refresh_calls == ["refresh"]


def test_job_finish_clears_runtime_status() -> None:
    controller, _fake_service = _build_controller()
    refresh_calls: list[str] = []
    history_calls: list[str] = []
    controller._run_in_gui_thread = lambda fn: fn()
    controller._request_queue_state_refresh = lambda: refresh_calls.append("refresh")
    controller._refresh_job_history = lambda: history_calls.append("history")
    controller.app_state.set_runtime_status(object())  # type: ignore[arg-type]

    controller._on_job_finished(Job(job_id="job-done"))

    assert controller.app_state.runtime_status is None
    assert history_calls == ["history"]
    assert refresh_calls == ["refresh"]


def test_job_failed_requests_queue_refresh() -> None:
    controller, _fake_service = _build_controller()
    refresh_calls: list[str] = []
    history_calls: list[str] = []
    controller._run_in_gui_thread = lambda fn: fn()
    controller._request_queue_state_refresh = lambda: refresh_calls.append("refresh")
    controller._refresh_job_history = lambda: history_calls.append("history")
    controller._handle_structured_job_failure = lambda _job: None
    controller.app_state.set_runtime_status(object())  # type: ignore[arg-type]

    controller._on_job_failed(Job(job_id="job-failed"))

    assert controller.app_state.runtime_status is None
    assert history_calls == ["history"]
    assert refresh_calls == ["refresh"]
