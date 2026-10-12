"""PR-BATCH-OPS-201: repository-backed batch discovery, progress, persistence and WebUI-hold truth.

Temporary SQLite, synthetic NJRs / the real Review and Video builders, a FIFO driver standing in for the
runner (and one real ``SingleNodeJobRunner`` with a fake backend callable). No process, GPU or user data.
"""

from __future__ import annotations

import time

import pytest

from src.controller.app_controller import AppController
from src.controller.job_history_service import JobHistoryService
from src.controller.job_service import JobService
from src.controller.review_batch_service import prepare_review_batch
from src.queue.batch_membership import BATCH_SCHEMA, BatchKey, BatchKind
from src.queue.batch_projection import BatchAggregateState, OutputKind
from src.queue.job_model import JobStatus, StageCheckpoint
from src.queue.single_node_runner import SingleNodeJobRunner
from src.utils.watchdog_v2 import WatchdogConfig
from tests.gui_v2.test_review_batch_200 import images as review_images
from tests.helpers.batch_ops_201 import (
    admit,
    image_file,
    make_stack,
    plain_njr,
    review_njr,
    settle_fifo,
    video_njr,
)
from tests.helpers.njr_factory import make_pipeline_njr
from tests.video.test_pr_vid_batch_200_multisource import _form, _stack
from tests.video.test_pr_vid_batch_200_multisource import _images as video_images


def _review_batch(stack, batch_id, count, **kwargs):
    jobs = [review_njr(f"{batch_id}-{i:02d}", batch_id, source_count=count, **kwargs) for i in range(count)]
    admit(stack, jobs)
    return BatchKey(BatchKind.REVIEW, batch_id), jobs


def _video_batch(stack, batch_id, count, *, prefix=None):
    jobs = [video_njr(f"{prefix or batch_id}-{i:02d}", batch_id, i, count) for i in range(count)]
    admit(stack, jobs)
    return BatchKey(BatchKind.VIDEO_WORKFLOW, batch_id), jobs


@pytest.fixture
def stack(tmp_path):
    return make_stack(tmp_path)


def _summary(stack, key):
    summary = stack.operations.refresh().catalog.get(key)
    assert summary is not None
    return summary


# ------------------------------------------------------------------ real builders (criteria 1, 6)


def test_real_review_and_video_builders_normalize_to_their_batches(stack, tmp_path):
    controller = object.__new__(AppController)
    controller._append_log = lambda _: None
    (tmp_path / "review").mkdir()
    sources = review_images(tmp_path / "review", 10)
    preview = prepare_review_batch(
        controller, image_paths=[str(p) for p in sources], stages=["img2img"],
        fallback_config={"model": "m.safetensors", "steps": 20, "cfg_scale": 7,
                         "img2img": {"denoising_strength": 0.3}},
        batch_size=4,
    )
    admit(stack, list(preview.jobs))
    video_controller, _ = _stack(tmp_path, job_service=stack.service)
    selection = video_controller.select_batch_sources([str(p) for p in video_images(tmp_path, 10)])
    plan = video_controller.preview_batch(sources=selection.sources, form_data=_form())
    assert plan.eligible, plan.assessment.problems
    admit(stack, list(plan.njrs))

    catalog = stack.operations.refresh().catalog
    review = catalog.get(BatchKey(BatchKind.REVIEW, preview.batch_id))
    video = catalog.get(BatchKey(BatchKind.VIDEO_WORKFLOW, plan.batch_id))
    # Review: explicit batch_size > 1 -> fewer jobs than sources; the two counts stay separate.
    assert review.job_count == 9 and review.declared_source_count == 10
    assert review.covered_source_count == 10
    assert any(len(job.source_paths) > 1 for job in review.jobs)
    assert all(job.source_index is None for job in review.jobs)
    # Video: one job per source, zero-based positions, declared count, workflow label.
    assert video.job_count == 10 and video.declared_source_count == 10
    assert [job.source_index for job in video.jobs] == list(range(10))
    assert video.jobs[0].model_label and video.jobs[0].source_label == "img_00.png"
    assert video.workload_kinds == ("video",)
    assert len(catalog.summaries) == 2 and not catalog.ambiguous_job_ids


# ------------------------------------------------------------------ membership in a mixed repository (2, 3)


def test_batch_kind_plus_id_prevents_collisions_and_ordinary_jobs_stay_ungrouped(stack):
    review_key, _ = _review_batch(stack, "shared-id", 3)
    video_key, _ = _video_batch(stack, "shared-id", 2, prefix="video-shared")
    admit(stack, [plain_njr("ordinary-1"), plain_njr("ordinary-2")])
    # Legacy-looking records: a bare top-level id and a descriptor without a valid kind.
    admit(stack, [
        make_pipeline_njr(job_id="legacy-bare", extra_metadata={"batch_id": "legacy"}),
        make_pipeline_njr(job_id="legacy-kind", extra_metadata={"batch": {
            "schema": BATCH_SCHEMA, "batch_id": "legacy", "batch_kind": "pack_name",
            "source_index": 0, "source_count": 1}}),
    ])
    catalog = stack.operations.refresh().catalog
    assert {s.key for s in catalog.summaries} == {review_key, video_key}
    assert catalog.get(review_key).job_count == 3 and catalog.get(video_key).job_count == 2
    members = {job.job_id for s in catalog.summaries for job in s.jobs}
    assert not members & {"ordinary-1", "ordinary-2", "legacy-bare", "legacy-kind"}


def test_contradictory_identifiers_are_excluded_and_reported(stack):
    key, _ = _review_batch(stack, "good", 2)
    admit(stack, [make_pipeline_njr(job_id="clash", extra_metadata={
        "review_batch": {"batch_id": "good", "source_count": 2}, "batch_id": "different"})])
    catalog = stack.operations.refresh().catalog
    assert catalog.ambiguous_job_ids == ("clash",)
    assert [job.job_id for job in catalog.get(key).jobs] == ["good-00", "good-01"]


def test_duplicate_positions_or_declared_counts_mark_the_batch_conflicting(stack):
    jobs = [video_njr("a", "dup", 0, 3), video_njr("b", "dup", 0, 3), video_njr("c", "dup", 2, 4)]
    admit(stack, jobs)
    summary = _summary(stack, BatchKey(BatchKind.VIDEO_WORKFLOW, "dup"))
    assert summary.conflicting and summary.declared_source_count is None
    assert len(summary.notes) >= 2


def test_missing_declared_members_are_noted_for_one_job_per_source_kinds(stack):
    admit(stack, [video_njr(f"m{i}", "short", i, 5) for i in (0, 1, 3)])
    summary = _summary(stack, BatchKey(BatchKind.VIDEO_WORKFLOW, "short"))
    assert summary.missing_member_count == 2 and not summary.conflicting
    assert any("2 declared" in note for note in summary.notes)


# ------------------------------------------------------------------ persistence (4, 5)


def test_reopened_sqlite_reconstructs_the_same_batch(stack):
    key, jobs = _video_batch(stack, "persist", 12)
    settle_fifo(stack, {3: "failed"}, count=6)
    before = _summary(stack, key)
    reopened = stack.reopen()
    after = reopened.operations.refresh().catalog.get(key)
    assert after.counts == before.counts and after.state == before.state
    assert [j.job_id for j in after.jobs] == [j.job_id for j in before.jobs]
    assert [j.status for j in after.jobs] == [j.status for j in before.jobs]
    assert after.first_created_at == before.first_created_at
    reopened.repository.close()


def test_recent_twenty_history_never_truncates_a_twenty_five_job_batch(stack):
    key, jobs = _review_batch(stack, "big", 25)
    settle_fifo(stack)
    history = JobHistoryService(stack.queue, stack.repository)
    assert len(history.list_recent_jobs(limit=20)) == 20  # the ordinary history view is capped...
    summary = _summary(stack, key)
    assert summary.job_count == 25 and summary.counts.completed == 25  # ...the batch view is not


def test_pagination_covers_every_member_and_reports_truncation(tmp_path):
    paged = make_stack(tmp_path, page_size=7)
    key, _ = _video_batch(paged, "pages", 25)
    snapshot = paged.operations.refresh()
    assert snapshot.catalog.get(key).job_count == 25 and not snapshot.catalog.truncated
    capped = make_stack(tmp_path, name="capped.sqlite3", page_size=5, max_candidates=10)
    _video_batch(capped, "pages", 25)
    assert capped.operations.refresh().catalog.truncated


# ------------------------------------------------------------------ status truth (7-10)


def test_every_canonical_status_is_counted_exactly(stack):
    key, jobs = _review_batch(stack, "mix", 10)
    claimed = []
    for ordinal in range(10):
        job = stack.queue.claim_next_job()
        claimed.append(job.job_id)
        if ordinal in (0, 1):
            stack.queue.mark_completed(job.job_id, {"success": True})
        elif ordinal in (2, 3):
            stack.queue.mark_failed(job.job_id, "synthetic")
        elif ordinal in (4, 5):
            stack.queue.mark_cancelled(job.job_id, "synthetic")
        elif ordinal == 6:
            break  # stays RUNNING
    summary = _summary(stack, key)
    counts = summary.counts
    assert (counts.completed, counts.failed, counts.cancelled, counts.running, counts.queued) == (
        2, 2, 2, 1, 3)
    assert counts.total == summary.job_count == 10 and summary.state is BatchAggregateState.ACTIVE
    for job_id in claimed:
        assert stack.repository.get_job(job_id).status == summary.job(job_id).status


def test_job_seven_of_twenty_five_fails_and_the_rest_continue_through_the_real_runner(tmp_path):
    repository_stack = make_stack(tmp_path)
    jobs = [video_njr(f"r-{i:02d}", "run", i, 25) for i in range(25)]
    order: list[str] = []

    def backend(job):
        order.append(job.job_id)
        if job.job_id == "r-06":
            return {"success": False, "error": "synthetic backend rejection"}
        return {"success": True, "variants": [], "metadata": {}}

    queue = repository_stack.queue
    runner = SingleNodeJobRunner(queue, run_callable=backend, poll_interval=0.01)
    service = JobService(queue, runner, watchdog_config=WatchdogConfig(enabled=False))
    service.set_auto_run_enabled(True)  # continuous dispatch, as in production; admission starts the runner
    service.submit_njrs(jobs)
    deadline = time.monotonic() + 30
    while len(order) < 25 and time.monotonic() < deadline:
        time.sleep(0.02)
    while queue.list_active_jobs_ordered() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert runner.stop(5) is True
    assert order == [f"r-{i:02d}" for i in range(25)]
    summary = _summary(repository_stack, BatchKey(BatchKind.VIDEO_WORKFLOW, "run"))
    assert summary.counts.failed == 1 and summary.counts.completed == 24
    assert summary.state is BatchAggregateState.COMPLETED_WITH_FAILURES
    assert summary.jobs[6].job_id == "r-06" and summary.jobs[6].failure.summary


def test_webui_held_images_stay_queued_while_independent_video_progresses(stack):
    image_key, _ = _review_batch(stack, "img", 4)
    video_key, _ = _video_batch(stack, "vid", 3)
    assert stack.queue.hold_webui_dispatch(reason="webui_pre_dispatch_unavailable", incident_id="inc-1")
    claimed = settle_fifo(stack, count=3)
    assert claimed and all(job_id.startswith("vid-") for job_id in claimed)
    snapshot = stack.operations.refresh()
    images, videos = snapshot.catalog.get(image_key), snapshot.catalog.get(video_key)
    assert snapshot.webui_hold["incident_id"] == "inc-1"
    assert images.counts.queued == 4 and images.held_count == 4  # annotation, not a sixth status
    assert videos.counts.completed == 3 and videos.held_count == 0
    assert all(job.status is JobStatus.QUEUED for job in images.jobs)
    assert stack.queue.release_webui_dispatch()
    refreshed = stack.operations.refresh()
    assert refreshed.catalog.get(image_key).held_count == 0 and refreshed.webui_hold is None


def test_partial_artifacts_stay_discoverable_on_a_failed_job(stack, tmp_path):
    key, _ = _review_batch(stack, "partial", 3)
    produced = image_file(tmp_path / "out" / "stage1.png")
    gone = tmp_path / "out" / "vanished.png"
    job = stack.queue.claim_next_job()
    stack.queue.publish_result(
        job.job_id, status=JobStatus.FAILED,
        result={"success": False, "error": "stage 2 failed", "variants": [], "metadata": {
            "completed_output_paths": [str(produced)]}},
        stage_checkpoints=[StageCheckpoint("txt2img", output_paths=[str(produced), str(gone)])],
        error_message="stage 2 failed",
    )
    failed = stack.operations.refresh(key).selected.job(job.job_id)
    assert failed.status is JobStatus.FAILED and failed.has_outputs
    by_path = {ref.path: ref for ref in failed.artifacts}
    assert by_path[str(produced)].available is True and by_path[str(produced)].kind is OutputKind.IMAGE
    assert by_path[str(gone)].available is False
    assert [c.stage_name for c in failed.checkpoints] == ["txt2img"]
    resolution = stack.operations.resolve_outputs(key, [job.job_id])
    assert resolution.images == (str(produced),)
    assert resolution.unavailable == ((job.job_id, str(gone), "missing or moved"),)


def test_a_corrupt_stored_record_is_listed_without_hiding_the_rest(stack):
    key, jobs = _video_batch(stack, "corrupt", 3)
    snapshot = stack.repository.get_job_model(jobs[1].job_id).snapshot
    snapshot["normalized_job"]["workload"] = "broken"
    import json

    stack.repository._connection.execute(
        "UPDATE jobs SET njr_snapshot = ? WHERE job_id = ?", (json.dumps(snapshot), jobs[1].job_id))
    summary = _summary(stack, key)
    assert summary.job_count == 3
    assert summary.job(jobs[1].job_id).hydration_error
    assert summary.job(jobs[0].job_id).hydration_error is None
