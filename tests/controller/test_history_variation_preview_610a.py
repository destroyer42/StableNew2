"""PR-HISTORY-610A: the Pipeline variation draft uses the one accepted-Preview admission contract.

Real ``AppStateV2`` + real ``PipelineController`` compile/admission + real ``JobService`` over temporary SQLite and a fake
runner. No GPU, WebUI, model or display. Deterministic: no sleeps.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.controller.job_service import JobService
from src.controller.pipeline_controller import PipelineController
from src.controller.pipeline_controller_services.history_handoff_service import (
    HistoryHandoffService,
)
from src.controller.pipeline_controller_services.preview_admission import (
    PreviewSupersededError,
    accepted_preview_records,
)
from src.gui.app_state_v2 import AppStateV2, PackJobEntry
from src.image_backends.operation_compatibility import OperationNotSupportedError
from src.pipeline import history_variation_compiler as hvc
from src.pipeline.history_variation_compiler import HistoryVariationDraft
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from tests.controller.test_job_service_unit import FakeRunner
from tests.pipeline.test_history_variation_compiler_610a import _source


class Harness:
    def __init__(self, tmp_path: Path) -> None:
        self.repository = JobRepository(tmp_path / "jobs.sqlite3")
        self.queue = JobQueue(repository=self.repository)
        self.service = JobService(self.queue, runner=FakeRunner(), require_normalized_records=True)
        self.app_state = AppStateV2()
        controller = object.__new__(PipelineController)
        controller._job_service = self.service
        controller._app_state = self.app_state
        controller._last_run_config = None
        controller._app_controller = None
        controller.can_enqueue_learning_jobs = lambda _count: (True, "")
        controller._is_queue_submission_blocked = lambda: False
        controller._sort_jobs_by_model = lambda rows: rows
        self.controller = controller
        self.parent = _source()
        self.draft = HistoryVariationDraft.from_source(self.parent)

    def stored_job_ids(self) -> list[str]:
        rows = self.repository._connection.execute("SELECT job_id FROM jobs").fetchall()  # noqa: SLF001
        return [row["job_id"] for row in rows]

    def build_preview(self):
        """What the Pipeline tab's refresh does: capture one request, compile it, publish by revision."""
        request = self.controller.build_preview_request()
        records = self.controller.get_preview_jobs_for_request(request)
        return (
            request,
            records,
            self.app_state.accept_preview_result(records, revision=request.preview_revision),
        )


@pytest.fixture
def harness(tmp_path: Path) -> Harness:
    return Harness(tmp_path)


def test_variation_preview_is_one_pure_compile_of_the_frozen_source(harness):
    harness.app_state.begin_history_variation(harness.draft.with_edits(steps=44, seed=9))
    _request, records, accepted = harness.build_preview()
    assert accepted and len(records) == 1
    job = records[0]
    assert (job.steps, job.seed) == (44, 9)
    assert job.source.parent_job_id == harness.parent.job_id and job.job_id != harness.parent.job_id
    assert harness.app_state.preview_jobs == records
    assert harness.stored_job_ids() == []  # loading and previewing never queue anything


def test_confirmation_admits_exactly_the_accepted_preview_once_and_clears_only_the_variation(
    harness,
):
    harness.app_state.begin_history_variation(harness.draft.with_edits(steps=44))
    _request, records, _ = harness.build_preview()
    compiles = []
    real = hvc.compile_history_variation
    harness.controller.get_preview_jobs = lambda: compiles.append(1) or real(
        harness.draft
    )  # must not run

    assert harness.controller.enqueue_draft_jobs(run_config={"run_mode": "queue"}) == 1

    assert compiles == []  # the frozen Preview record is admitted; nothing is recompiled at submit
    assert harness.stored_job_ids() == [records[0].job_id]
    stored = harness.repository.get_job(records[0].job_id).snapshot["normalized_job"]
    assert stored["source"]["parent_job_id"] == harness.parent.job_id
    assert stored["source"]["kind"] == "history_replay"
    assert stored["workload"]["config"]["steps"] == 44
    assert harness.app_state.job_draft.history_variation is None
    assert harness.app_state.preview_jobs == []


def test_editing_after_preview_invalidates_it_and_a_superseded_compile_cannot_publish(harness):
    harness.app_state.begin_history_variation(harness.draft)
    request, stale_records, accepted = harness.build_preview()
    assert accepted
    assert harness.app_state.update_history_variation(harness.draft.with_edits(cfg_scale=9.0))
    assert harness.app_state.preview_jobs == []
    # a compile that started before the edit may not republish the old values
    assert (
        harness.app_state.accept_preview_result(stale_records, revision=request.preview_revision)
        is False
    )
    assert harness.app_state.preview_jobs == []
    _request2, fresh, ok = harness.build_preview()
    assert ok and fresh[0].cfg_scale == 9.0


def test_admission_compile_superseded_by_an_edit_is_refused_and_queues_nothing(harness):
    harness.app_state.begin_history_variation(harness.draft)
    edited = harness.draft.with_edits(steps=51)

    def compile_then_edit():
        records = hvc.compile_history_variation(harness.draft)
        harness.app_state.update_history_variation(
            edited
        )  # the operator edits while the compile runs
        return [records]

    with pytest.raises(PreviewSupersededError):
        accepted_preview_records(harness.app_state, compile_then_edit)
    assert harness.stored_job_ids() == [] and harness.app_state.preview_jobs == []
    assert harness.app_state.job_draft.history_variation == edited


def test_switching_drafts_drops_the_old_preview_and_it_cannot_be_admitted(harness):
    harness.app_state.begin_history_variation(harness.draft)
    request, old_records, _ = harness.build_preview()
    harness.app_state.clear_job_draft()  # back to a normal (empty) draft
    assert harness.app_state.job_draft.history_variation is None
    assert harness.app_state.preview_jobs == []
    assert (
        harness.app_state.accept_preview_result(old_records, revision=request.preview_revision)
        is False
    )
    claimed, _revision = harness.app_state.claim_preview_for_admission()
    assert claimed == []
    harness.app_state.begin_history_variation(harness.draft)
    harness.app_state.add_packs_to_job_draft(
        [PackJobEntry("p", "p", {})]
    )  # a pack draft, then Replace again
    harness.app_state.begin_history_variation(harness.draft)
    assert harness.app_state.job_draft.packs == []


def test_adding_a_pack_or_part_supersedes_the_variation_so_draft_modes_never_mix(harness):
    harness.app_state.begin_history_variation(harness.draft)
    harness.app_state.add_packs_to_job_draft([PackJobEntry("p", "p", {})])
    assert harness.app_state.job_draft.history_variation is None
    assert [entry.pack_id for entry in harness.app_state.job_draft.packs] == ["p"]
    harness.app_state.begin_history_variation(harness.draft)
    harness.app_state.add_job_draft_part("a part", "")
    assert harness.app_state.job_draft.history_variation is None
    assert harness.app_state.job_draft.summary.part_count == 1


def test_replace_decision_helper_reports_unsent_pipeline_work(harness):
    assert harness.app_state.has_unsent_pipeline_work() is False
    harness.app_state.add_packs_to_job_draft([PackJobEntry("p", "p", {})])
    assert harness.app_state.has_unsent_pipeline_work() is True
    harness.app_state.clear_job_draft()
    harness.app_state.begin_history_variation(harness.draft)
    assert harness.app_state.has_unsent_pipeline_work() is True


def test_refusal_at_compile_admits_zero_jobs_and_reports_the_reason(harness, monkeypatch):
    harness.app_state.begin_history_variation(harness.draft)
    blocked = type(
        "A", (), {"ready": False, "explain": lambda self: "model changed", "problems": ()}
    )()
    monkeypatch.setattr(hvc, "assess_njr", lambda job: blocked)
    request, records, accepted = harness.build_preview()
    assert records == [] and accepted
    assert "model changed" in harness.controller.get_preview_build_timing_snapshot()["error"]
    assert harness.controller.enqueue_draft_jobs() == 0
    assert harness.stored_job_ids() == []
    assert harness.app_state.job_draft.history_variation is not None  # nothing was lost
    with pytest.raises(OperationNotSupportedError):
        hvc.compile_history_variation(harness.draft)


def test_submission_failure_admits_zero_jobs_and_keeps_the_draft(harness, monkeypatch):
    harness.app_state.begin_history_variation(harness.draft)
    harness.build_preview()

    def boom(*_a, **_k):
        raise RuntimeError("queue down")

    monkeypatch.setattr(harness.service, "submit_njrs", boom)
    with pytest.raises(RuntimeError):
        harness.controller.enqueue_draft_jobs()
    assert harness.stored_job_ids() == []
    assert harness.app_state.job_draft.history_variation is not None
    assert harness.app_state.preview_jobs  # the accepted Preview is still there to retry


def test_add_to_queue_v2_routes_a_variation_through_the_accepted_preview(harness):
    harness.app_state.begin_history_variation(harness.draft)
    _request, records, _ = harness.build_preview()
    published = []
    real_set = harness.app_state.set_preview_jobs
    harness.app_state.set_preview_jobs = lambda jobs, **kw: published.append(jobs) or real_set(
        jobs, **kw
    )
    harness.controller.on_add_job_to_queue_v2()
    assert published == []  # the unguarded set_preview_jobs shortcut is never used
    assert harness.stored_job_ids() == [records[0].job_id]


def test_exact_replay_is_unchanged_by_an_active_variation_draft(harness):
    harness.app_state.begin_history_variation(harness.draft.with_edits(steps=44))
    request, records, _ = harness.build_preview()
    before = (harness.app_state.job_draft.history_variation, list(harness.app_state.preview_jobs))
    submitted = []

    class History:
        def get_job(self, job_id):
            from datetime import datetime

            from src.queue.job_history_store import JobHistoryEntry
            from src.queue.job_model import JobStatus

            return JobHistoryEntry(
                job_id=job_id,
                created_at=datetime.utcnow(),
                status=JobStatus.COMPLETED,
                snapshot={"normalized_job": harness.parent.to_dict()},
            )

    count = HistoryHandoffService().replay_job_from_history(
        job_id=harness.parent.job_id,
        history_service=History(),
        submit_normalized_jobs=lambda recs, **kw: submitted.extend(recs) or len(recs),
    )
    assert count == 1
    (replayed,) = submitted
    assert replayed.source.kind.value == "history_replay"
    assert "history_variation" not in replayed.source.to_dict()["metadata"]
    assert replayed.config["steps"] == harness.parent.config["steps"]  # exact: no edits applied
    assert (
        harness.app_state.job_draft.history_variation,
        list(harness.app_state.preview_jobs),
    ) == before
