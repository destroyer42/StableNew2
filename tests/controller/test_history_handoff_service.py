from __future__ import annotations

from datetime import datetime

import pytest

from src.controller.pipeline_controller_services.history_handoff_service import (
    HistoryHandoffService,
)
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.queue.job_history_store import (
    INTERRUPTED_RESTART_ACTION_REQUIRED,
    JobHistoryEntry,
)
from src.queue.job_model import Job, JobPriority, JobStatus
from src.utils.error_envelope_v2 import UnifiedErrorEnvelope
from src.utils.snapshot_builder_v2 import build_job_snapshot
from tests.helpers.job_helpers import make_test_njr


class _HistoryServiceStub:
    def __init__(self, entry: JobHistoryEntry) -> None:
        self._entry = entry

    def get_job(self, job_id: str) -> JobHistoryEntry | None:
        if job_id == self._entry.job_id:
            return self._entry
        return None

    def get_history_record(self, job_id: str) -> JobHistoryEntry | None:
        return self.get_job(job_id)


class _AppStateStub:
    def __init__(self) -> None:
        self.preview_jobs = None

    def set_preview_jobs(self, jobs):
        self.preview_jobs = list(jobs or [])


def _make_entry(
    record: NormalizedJobRecord,
    *,
    status: JobStatus = JobStatus.COMPLETED,
) -> JobHistoryEntry:
    job = Job(
        job_id=record.job_id,
        config_snapshot=record.to_queue_snapshot(),
        run_mode="queue",
        source="gui",
        prompt_source="manual",
        priority=JobPriority.NORMAL,
        status=status,
    )
    snapshot = build_job_snapshot(
        job, record, run_config={"run_mode": "queue", "source": "history"}
    )
    return JobHistoryEntry(
        job_id=job.job_id,
        created_at=datetime.utcnow(),
        status=status,
        payload_summary="",
        snapshot=snapshot,
    )


def test_history_handoff_service_replays_snapshot_to_submit_callback() -> None:
    record = make_test_njr(
        job_id="history-job",
        prompt="a",
        prompt_source="manual",
        prompt_pack_id="",
        config={"model": "sdxl", "prompt": "a", "negative_prompt": "b"},
    )
    entry = _make_entry(record)
    history_service = _HistoryServiceStub(entry)
    submissions: list[tuple[list[NormalizedJobRecord], dict[str, object], str, str]] = []

    service = HistoryHandoffService()

    queued = service.replay_job_from_history(
        job_id="history-job",
        history_service=history_service,
        submit_normalized_jobs=lambda records,
        run_config=None,
        source="gui",
        prompt_source="manual": (
            submissions.append((list(records), dict(run_config or {}), source, prompt_source))
            or len(records)
        ),
    )

    assert queued == 1
    assert submissions[0][0][0].job_id != "history-job"
    assert submissions[0][0][0].source.parent_job_id == "history-job"
    assert submissions[0][1]["run_mode"] == "queue"
    assert submissions[0][2] == "history_replay"


def test_interrupted_history_replay_creates_new_identity_with_parent_lineage() -> None:
    record = make_test_njr(
        job_id="interrupted-job",
        prompt="a",
        prompt_source="manual",
        prompt_pack_id="",
        config={"model": "sdxl", "prompt": "a", "negative_prompt": "b"},
    )
    entry = _make_entry(record, status=JobStatus.FAILED)
    entry.error_envelope = UnifiedErrorEnvelope(
        error_type=INTERRUPTED_RESTART_ACTION_REQUIRED,
        subsystem="queue_recovery",
        severity="ERROR",
        message="action required",
        cause=None,
        stack="",
        job_id=entry.job_id,
        stage="txt2img",
    )
    history_service = _HistoryServiceStub(entry)
    submissions: list[NormalizedJobRecord] = []

    queued = HistoryHandoffService().replay_job_from_history(
        job_id=entry.job_id,
        history_service=history_service,
        submit_normalized_jobs=lambda records, **_kwargs: (
            submissions.extend(records) or len(records)
        ),
    )

    assert queued == 1
    assert entry.status == JobStatus.FAILED
    assert len(submissions) == 1
    assert submissions[0].job_id != entry.job_id
    assert submissions[0].source.parent_job_id == entry.job_id


@pytest.mark.parametrize("outcome", [0, 1, RuntimeError("admission failed")])
def test_replay_preserves_pipeline_state_for_every_admission_outcome(outcome) -> None:
    from src.controller.pipeline_controller import PipelineController
    from src.gui.app_state_v2 import AppStateV2

    parent = make_test_njr(job_id="parent", prompt_source="manual", prompt_pack_id="")
    draft = make_test_njr(job_id="current-preview")
    state = AppStateV2()
    state.set_preview_jobs([draft], error="existing diagnostic")
    revision = state.preview_revision
    controller = object.__new__(PipelineController)
    controller._app_state = state
    controller._last_run_config = {"source": "current-draft"}
    controller.get_job_history_service = lambda: _HistoryServiceStub(_make_entry(parent))
    submitted = []

    def admit(records, **kwargs):
        submitted.extend(records)
        assert state.preview_jobs == [draft]
        assert kwargs["source"] == "history_replay"
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    controller._submit_normalized_jobs = admit
    if isinstance(outcome, Exception):
        with pytest.raises(RuntimeError, match="admission failed"):
            controller.replay_job_from_history(parent.job_id)
    else:
        assert controller.replay_job_from_history(parent.job_id) == outcome
    assert len(submitted) == 1
    assert submitted[0].job_id != parent.job_id
    assert state.preview_jobs == [draft]
    assert state.preview_error == "existing diagnostic"
    assert state.preview_revision == revision
    assert controller._last_run_config == {"source": "current-draft"}
