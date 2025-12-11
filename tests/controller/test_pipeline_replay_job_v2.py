from __future__ import annotations

from datetime import datetime

from src.controller.pipeline_controller import PipelineController
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.queue.job_history_store import JobHistoryEntry
from src.queue.job_model import Job, JobPriority, JobStatus
from src.utils.snapshot_builder_v2 import build_job_snapshot


class DummyJobService:
    def __init__(self) -> None:
        self.submitted: list[Job] = []

    def submit_job_with_run_mode(self, job: Job) -> None:
        self.submitted.append(job)


class DummyHistoryService:
    def __init__(self, entry: JobHistoryEntry) -> None:
        self._entry = entry

    def get_job(self, job_id: str) -> JobHistoryEntry | None:
        if job_id == self._entry.job_id:
            return self._entry
        return None


class DummyAppState:
    def __init__(self) -> None:
        self.preview_jobs: list[NormalizedJobRecord] | None = None

    def set_preview_jobs(self, jobs: list[NormalizedJobRecord] | None) -> None:
        self.preview_jobs = list(jobs or [])


class DummyPipelineController(PipelineController):
    def __init__(self) -> None:
        pass


def _make_snapshot_entry(record: NormalizedJobRecord) -> tuple[JobHistoryEntry, Job]:
    job = Job(
        job_id=record.job_id,
        config_snapshot=record.to_queue_snapshot(),
        run_mode="queue",
        source="gui",
        prompt_source="manual",
        priority=JobPriority.NORMAL,
        status=JobStatus.COMPLETED,
    )
    snapshot = build_job_snapshot(job, record, run_config={"run_mode": "queue"})
    entry = JobHistoryEntry(
        job_id=job.job_id,
        created_at=datetime.utcnow(),
        status=JobStatus.COMPLETED,
        payload_summary="",
        snapshot=snapshot,
    )
    return entry, job


def test_replay_job_from_history_submits_snapshot_job():
    record = NormalizedJobRecord(
        job_id="replay-job",
        config={"model": "md", "prompt": "s", "negative_prompt": "n"},
        path_output_dir="out",
        filename_template="{seed}",
        seed=99,
    )
    entry, _ = _make_snapshot_entry(record)
    history_service = DummyHistoryService(entry)
    controller = object.__new__(DummyPipelineController)
    controller._job_service = DummyJobService()
    controller._app_state = DummyAppState()
    controller._learning_enabled = False
    controller._run_job = lambda job: {}
    controller.get_job_history_service = lambda: history_service
    controller.state_manager = None  # not used

    queued = controller.replay_job_from_history(record.job_id)

    assert queued == 1
    assert controller._app_state.preview_jobs
    assert controller._app_state.preview_jobs[0].job_id == record.job_id
    assert len(controller._job_service.submitted) == 1
    assert controller._job_service.submitted[0].job_id == record.job_id
