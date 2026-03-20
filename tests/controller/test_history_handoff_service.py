from __future__ import annotations

from datetime import datetime

from src.controller.pipeline_controller_services.history_handoff_service import (
    HistoryHandoffService,
)
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.queue.job_history_store import JobHistoryEntry
from src.queue.job_model import Job, JobPriority, JobStatus
from src.utils.snapshot_builder_v2 import build_job_snapshot


class _HistoryServiceStub:
    def __init__(self, entry: JobHistoryEntry) -> None:
        self._entry = entry

    def get_job(self, job_id: str) -> JobHistoryEntry | None:
        if job_id == self._entry.job_id:
            return self._entry
        return None


class _AppStateStub:
    def __init__(self) -> None:
        self.preview_jobs = None

    def set_preview_jobs(self, jobs):
        self.preview_jobs = list(jobs or [])


def _make_entry(record: NormalizedJobRecord) -> JobHistoryEntry:
    job = Job(
        job_id=record.job_id,
        config_snapshot=record.to_queue_snapshot(),
        run_mode="queue",
        source="gui",
        prompt_source="manual",
        priority=JobPriority.NORMAL,
        status=JobStatus.COMPLETED,
    )
    snapshot = build_job_snapshot(job, record, run_config={"run_mode": "queue", "source": "history"})
    return JobHistoryEntry(
        job_id=job.job_id,
        created_at=datetime.utcnow(),
        status=JobStatus.COMPLETED,
        payload_summary="",
        snapshot=snapshot,
    )


def test_history_handoff_service_replays_snapshot_to_submit_callback() -> None:
    record = NormalizedJobRecord(
        job_id="history-job",
        config={"model": "sdxl", "prompt": "a", "negative_prompt": "b"},
        path_output_dir="out",
        filename_template="{seed}",
        seed=7,
    )
    entry = _make_entry(record)
    history_service = _HistoryServiceStub(entry)
    app_state = _AppStateStub()
    submissions: list[tuple[list[NormalizedJobRecord], dict[str, object], str, str]] = []
    last_run_configs: list[dict[str, object]] = []

    service = HistoryHandoffService()

    queued = service.replay_job_from_history(
        job_id="history-job",
        history_service=history_service,
        app_state=app_state,
        submit_normalized_jobs=lambda records, run_config=None, source="gui", prompt_source="manual": (
            submissions.append((list(records), dict(run_config or {}), source, prompt_source)) or len(records)
        ),
        set_last_run_config=lambda cfg: last_run_configs.append(dict(cfg)),
    )

    assert queued == 1
    assert app_state.preview_jobs[0].job_id == "history-job"
    assert submissions[0][0][0].job_id == "history-job"
    assert submissions[0][1]["run_mode"] == "queue"
    assert last_run_configs[0]["source"] == "history"
