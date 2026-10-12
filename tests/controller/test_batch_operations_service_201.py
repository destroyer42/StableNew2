"""PR-BATCH-OPS-201: selected retry (explicit new identities), failure safety and output navigation."""

from __future__ import annotations

import hashlib
import threading

import pytest

from src.controller.batch_operations_service import BatchOperationRefused
from src.controller.job_history_service import JobHistoryService
from src.controller.pipeline_controller_services.history_handoff_service import (
    HistoryHandoffService,
)
from src.queue.batch_membership import BatchKey, BatchKind, replay_origin_of
from src.queue.batch_projection import snapshot_metadata
from src.queue.job_model import JobStatus
from tests.helpers.batch_ops_201 import (
    admit,
    image_file,
    make_stack,
    review_njr,
    settle_fifo,
    status_of,
    video_njr,
)

REVIEW = BatchKey(BatchKind.REVIEW, "rev")
VIDEO = BatchKey(BatchKind.VIDEO_WORKFLOW, "vid")


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _unknown():
    return {"success": False, "error": "response lost", "metadata": {"failure_evidence": {
        "contract": "webui_failure_evidence/1", "error_code": "outcome_unknown",
        "request_may_have_executed": True, "stage": "img2img"}}}


def _unavailable():
    return {"success": False, "error": "no route", "metadata": {"failure_evidence": {
        "contract": "webui_failure_evidence/1", "error_code": "connection_error",
        "webui_unavailable": True, "stage": "img2img"}}}


@pytest.fixture
def stack(tmp_path):
    return make_stack(tmp_path)


@pytest.fixture
def review(stack, tmp_path):
    """Six Review jobs with real source images; jobs 0, 2 and 4 FAILED (typed, retry-safe evidence)."""

    sources = [image_file(tmp_path / "src" / f"s{i}.png", i) for i in range(6)]
    jobs = [review_njr(f"rev-{i}", "rev", source=sources[i], source_count=6,
                       artifact_sha256=_sha(sources[i])) for i in range(6)]
    admit(stack, jobs)
    settle_fifo(stack, {0: "failed", 2: "failed", 4: "failed"}, result=_unavailable())
    return stack, sources


def _snapshot_of(stack, job_id):
    return stack.repository.get_job(job_id).snapshot


# ------------------------------------------------------------------ explicit new identities (16-19, 25)


def test_three_selected_failures_become_three_new_identities_through_one_submit_njrs(review):
    stack, _ = review
    calls = []
    real = stack.service.submit_njrs
    stack.service.submit_njrs = lambda records, policy=None: calls.append(list(records)) or real(records, policy)
    before = {j: _snapshot_of(stack, j) for j in ("rev-0", "rev-2", "rev-4")}

    plan = stack.operations.preflight_retry(REVIEW, ["rev-0", "rev-2", "rev-4"])
    assert plan.submittable and [i.reasons for i in plan.items] == [(), (), ()]
    submission = stack.operations.submit_retry(plan)

    assert len(calls) == 1 and len(calls[0]) == 3  # ONE all-or-none admission for the whole selection
    assert [pair[0] for pair in submission.admitted] == ["rev-0", "rev-2", "rev-4"]
    new_ids = [pair[1] for pair in submission.admitted]
    assert len(set(new_ids)) == 3 and not set(new_ids) & {f"rev-{i}" for i in range(6)}
    for source_id, new_id in submission.admitted:
        job = stack.repository.get_job_model(new_id)
        assert job.status is JobStatus.QUEUED
        assert job._normalized_record.source.parent_job_id == source_id
        assert stack.repository.get_lineage(new_id)[0] == source_id
    # The failed originals are untouched: same status, same immutable snapshot, same error.
    for job_id, snapshot in before.items():
        assert status_of(stack, job_id) is JobStatus.FAILED and _snapshot_of(stack, job_id) == snapshot


def test_a_multi_job_retry_is_a_new_versioned_batch_and_the_origin_is_not_inherited(review):
    stack, _ = review
    submission = stack.operations.submit_retry(
        stack.operations.preflight_retry(REVIEW, ["rev-0", "rev-2", "rev-4"]))
    retry_key = submission.retry_batch
    assert retry_key.kind is BatchKind.SELECTED_RETRY and retry_key != REVIEW
    catalog = stack.operations.refresh(REVIEW).catalog
    original, retry = catalog.get(REVIEW), catalog.get(retry_key)
    # Distinguishable in every projection; the original is not double counted or enlarged.
    assert original.job_count == 6 and original.counts.failed == 3 and original.counts.queued == 0
    assert retry.job_count == 3 and retry.counts.queued == 3 and retry.declared_source_count == 3
    assert retry.origin_batch == REVIEW and retry.key.label.startswith("Retry ")
    for job in retry.jobs:
        origin = replay_origin_of(snapshot_metadata(_snapshot_of(stack, job.job_id)))
        assert origin.key == REVIEW
    assert [j.source_index for j in retry.jobs] == [0, 1, 2]
    assert not set(catalog.ambiguous_job_ids)


def test_a_single_retry_is_an_ordinary_replay_child_with_no_batch(review):
    stack, _ = review
    submission = stack.operations.submit_retry(stack.operations.preflight_retry(REVIEW, ["rev-2"]))
    assert submission.retry_batch is None
    catalog = stack.operations.refresh(REVIEW).catalog
    assert len(catalog.summaries) == 1 and catalog.get(REVIEW).job_count == 6
    child = submission.admitted[0][1]
    assert child not in {j.job_id for s in catalog.summaries for j in s.jobs}
    detail = stack.operations.refresh(REVIEW).selected.job("rev-2")
    assert [c.job_id for c in detail.retry_children] == [child]  # relationship shown, not counted


def test_ordinary_single_replay_cannot_contaminate_the_original_batch(review):
    stack, _ = review
    history = JobHistoryService(stack.queue, stack.repository)
    submitted = []
    count = HistoryHandoffService().replay_job_from_history(
        job_id="rev-0", history_service=history, app_state=None,
        submit_normalized_jobs=lambda records, **_: submitted.extend(records) or len(stack.service.submit_njrs(records)),
        set_last_run_config=lambda _: None,
    )
    assert count == 1
    catalog = stack.operations.refresh().catalog
    assert catalog.get(REVIEW).job_count == 6 and len(catalog.summaries) == 1
    assert submitted[0].job_id not in {j.job_id for j in catalog.get(REVIEW).jobs}


def test_retry_children_are_found_after_restart_and_block_a_duplicate_retry(review):
    stack, _ = review
    submission = stack.operations.submit_retry(
        stack.operations.preflight_retry(REVIEW, ["rev-0", "rev-2"]))
    reopened = stack.reopen()
    snapshot = reopened.operations.refresh(REVIEW)
    retry = snapshot.catalog.get(submission.retry_batch)
    assert retry.job_count == 2 and retry.origin_batch == REVIEW
    detail = snapshot.selected
    assert {c.job_id for c in detail.job("rev-0").retry_children} == {submission.admitted[0][1]}
    again = reopened.operations.preflight_retry(REVIEW, ["rev-0", "rev-4"])
    assert not again.submittable
    assert "Already retried as" in again.items[0].reasons[0] and again.items[1].eligible
    reopened.repository.close()


# ------------------------------------------------------------------ preflight shows everything (23)


def test_ineligible_selections_are_listed_and_require_a_revised_selection(review):
    stack, _ = review
    plan = stack.operations.preflight_retry(REVIEW, ["rev-0", "rev-1", "rev-3", "elsewhere"])
    reasons = {item.job_id: item.reasons for item in plan.items}
    assert reasons["rev-0"] == ()
    assert "is completed" in reasons["rev-1"][0] and "only FAILED" in reasons["rev-1"][0]
    assert "Not a member" in reasons["elsewhere"][0]
    assert not plan.submittable and len(plan.items) == 4  # nothing silently dropped
    count = stack.repository.count()
    with pytest.raises(BatchOperationRefused, match="Revise the selection"):
        stack.operations.submit_retry(plan)
    assert stack.repository.count() == count


def test_missing_and_changed_sources_fail_preflight_without_partial_admission(review):
    stack, sources = review
    sources[0].unlink()
    sources[2].write_bytes(sources[2].read_bytes() + b"x")  # content changed, name unchanged
    plan = stack.operations.preflight_retry(REVIEW, ["rev-0", "rev-2", "rev-4"])
    assert "missing or was moved" in plan.items[0].reasons[0]
    assert "changed since the job was created" in plan.items[1].reasons[0]
    assert plan.items[2].eligible
    count = stack.repository.count()
    with pytest.raises(BatchOperationRefused):
        stack.operations.submit_retry(plan)
    assert stack.repository.count() == count


def test_sources_that_change_between_preflight_and_admission_are_caught_at_admission(review):
    stack, sources = review
    plan = stack.operations.preflight_retry(REVIEW, ["rev-0", "rev-2"])
    assert plan.submittable
    sources[2].write_bytes(b"replaced after the review dialog")
    count = stack.repository.count()
    with pytest.raises(BatchOperationRefused, match="changed since it was reviewed"):
        stack.operations.submit_retry(plan)
    assert stack.repository.count() == count


def test_a_failure_replayed_elsewhere_before_the_click_is_not_duplicated(review):
    stack, _ = review
    plan = stack.operations.preflight_retry(REVIEW, ["rev-0"])
    HistoryHandoffService().replay_job_from_history(
        job_id="rev-0", history_service=JobHistoryService(stack.queue, stack.repository),
        app_state=None, submit_normalized_jobs=lambda records, **_: len(stack.service.submit_njrs(records)),
        set_last_run_config=lambda _: None)
    count = stack.repository.count()
    with pytest.raises(BatchOperationRefused, match="Already retried"):
        stack.operations.submit_retry(plan)
    assert stack.repository.count() == count


# ------------------------------------------------------------------ all-or-none admission (18)


def test_a_later_item_admission_failure_leaves_zero_new_retry_jobs(review):
    stack, _ = review
    ids = iter(["fresh-id", "rev-1", "never-used"])  # the 2nd new identity collides with an existing job
    stack.operations._replay_id_fn = lambda: next(ids)
    plan = stack.operations.preflight_retry(REVIEW, ["rev-0", "rev-2", "rev-4"])
    before = set(stack.repository.identities())
    with pytest.raises(BatchOperationRefused, match="Nothing was admitted"):
        stack.operations.submit_retry(plan)
    assert set(stack.repository.identities()) == before and "fresh-id" not in before
    assert stack.queue.get_job("fresh-id") is None  # nor runnable in the queue projection


# ------------------------------------------------------------------ unknown outcome safety (21, 22)


def test_unknown_outcome_needs_explicit_specific_acknowledgement(stack, tmp_path):
    sources = [image_file(tmp_path / f"u{i}.png", i) for i in range(3)]
    admit(stack, [review_njr(f"u{i}", "rev", source=sources[i], source_count=3) for i in range(3)])
    settle_fifo(stack, {0: "failed", 1: "failed", 2: "failed"},
                results={0: _unknown(), 1: _unavailable(), 2: _unknown()})
    plan = stack.operations.preflight_retry(REVIEW, ["u0", "u1", "u2"])
    assert plan.submittable
    assert [i.job_id for i in plan.acknowledgements] == ["u0", "u2"]
    assert "may have produced output" in plan.acknowledgements[0].acknowledgement_text
    count = stack.repository.count()
    with pytest.raises(BatchOperationRefused, match="Acknowledgement required"):
        stack.operations.submit_retry(plan)
    with pytest.raises(BatchOperationRefused, match="Acknowledgement required"):
        stack.operations.submit_retry(plan, acknowledged_job_ids=["u0"])  # one of two is not enough
    assert stack.repository.count() == count
    submission = stack.operations.submit_retry(plan, acknowledged_job_ids=["u0", "u2"])
    assert len(submission.admitted) == 3


def test_nothing_is_replayed_automatically_and_restart_does_not_bypass_the_acknowledgement(
    stack, tmp_path
):
    source = image_file(tmp_path / "r.png")
    admit(stack, [review_njr("run", "rev", source=source, source_count=1)])
    stack.queue.claim_next_job()  # RUNNING when the application "exits"
    submit_calls = []
    real = stack.service.submit_njrs
    stack.service.submit_njrs = lambda *a, **k: submit_calls.append(a) or real(*a, **k)
    reopened = stack.reopen()  # startup recovery marks the interrupted job FAILED / ambiguous
    reopened.service.submit_njrs = lambda *a, **k: submit_calls.append(a)
    snapshot = reopened.operations.refresh(REVIEW)
    job = snapshot.selected.job("run")
    assert job.status is JobStatus.FAILED and job.failure.acknowledgement_required
    plan = reopened.operations.preflight_retry(REVIEW, ["run"])
    assert plan.acknowledgements and not submit_calls  # loading, classifying and planning submit nothing
    assert reopened.repository.count() == 1
    with pytest.raises(BatchOperationRefused, match="Acknowledgement required"):
        reopened.operations.submit_retry(plan)
    reopened.repository.close()


# ------------------------------------------------------------------ duplicate clicks / overlap (24)


def test_the_same_plan_cannot_be_admitted_twice(review):
    stack, _ = review
    plan = stack.operations.preflight_retry(REVIEW, ["rev-0", "rev-2"])
    stack.operations.submit_retry(plan)
    count = stack.repository.count()
    with pytest.raises(BatchOperationRefused, match="already submitted"):
        stack.operations.submit_retry(plan)
    assert stack.repository.count() == count


def test_overlapping_clicks_admit_exactly_once(review):
    stack, _ = review
    plans = [stack.operations.preflight_retry(REVIEW, ["rev-0", "rev-2"]) for _ in range(2)]
    gate, entered = threading.Event(), threading.Event()
    real = stack.service.submit_njrs

    def slow(records, policy=None):
        entered.set()
        gate.wait(5)
        return real(records, policy)

    stack.service.submit_njrs = slow
    results, errors = [], []

    def click(plan):
        try:
            results.append(stack.operations.submit_retry(plan))
        except BatchOperationRefused as exc:
            errors.append(str(exc))

    first = threading.Thread(target=click, args=(plans[0],))
    first.start()
    assert entered.wait(5)
    click(plans[1])  # second click lands while the first is mid-admission
    gate.set()
    first.join(5)
    assert len(results) == 1 and len(errors) == 1 and "already being submitted" in errors[0]
    new_children = [j for j in stack.repository.identities() if j not in {f"rev-{i}" for i in range(6)}]
    assert len(new_children) == 2


def test_two_separately_reviewed_plans_for_the_same_failure_admit_only_once(review):
    stack, _ = review
    first = stack.operations.preflight_retry(REVIEW, ["rev-4"])
    second = stack.operations.preflight_retry(REVIEW, ["rev-4"])
    stack.operations.submit_retry(first)
    with pytest.raises(BatchOperationRefused, match="Already retried"):
        stack.operations.submit_retry(second)


# ------------------------------------------------------------------ admission vs runner start (§ retry)


def test_durable_admission_is_reported_separately_from_a_runner_start_failure(review):
    stack, _ = review
    stack.service.set_auto_run_enabled(False)
    stack.service.auto_run_enabled = True
    stack.runner.fail_start = True
    submission = stack.operations.submit_retry(stack.operations.preflight_retry(REVIEW, ["rev-0", "rev-2"]))
    assert len(submission.admitted) == 2  # durable
    assert any("worker is not running" in note for note in submission.notes)
    assert {status_of(stack, pair[1]) for pair in submission.admitted} == {JobStatus.QUEUED}


def test_a_follow_up_error_after_commit_is_reported_as_admitted_not_as_a_failure(review):
    stack, _ = review

    def explode():
        raise RuntimeError("listener failed")

    stack.service._emit_queue_updated = explode
    submission = stack.operations.submit_retry(stack.operations.preflight_retry(REVIEW, ["rev-0", "rev-2"]))
    assert len(submission.admitted) == 2 and any("durably admitted" in n for n in submission.notes)
    assert {status_of(stack, pair[1]) for pair in submission.admitted} == {JobStatus.QUEUED}


def test_retries_respect_pause_auto_run_and_the_webui_hold(review):
    stack, _ = review
    stack.queue.pause()
    stack.queue.hold_webui_dispatch(reason="webui_outage", incident_id="i")
    submission = stack.operations.submit_retry(stack.operations.preflight_retry(REVIEW, ["rev-0", "rev-2"]))
    assert any("paused" in note for note in submission.notes) and stack.runner.started == 0
    stack.queue.resume()
    assert stack.queue.claim_next_job() is None  # image retries are held with the outage, still QUEUED
    assert {status_of(stack, pair[1]) for pair in submission.admitted} == {JobStatus.QUEUED}


# ------------------------------------------------------------------ video retries


def test_video_failures_retry_with_their_frozen_inputs_checked(stack, tmp_path):
    sources = [image_file(tmp_path / f"v{i}.png", i) for i in range(3)]
    admit(stack, [video_njr(f"v-{i}", "vid", i, 3, source=sources[i]) for i in range(3)])
    settle_fifo(stack, {1: "failed"}, result=_unavailable())
    plan = stack.operations.preflight_retry(VIDEO, ["v-1"])
    assert plan.submittable
    sources[1].unlink()
    assert "missing or was moved" in stack.operations.preflight_retry(VIDEO, ["v-1"]).items[0].reasons[0]
    sources[1].write_bytes(image_file(tmp_path / "again.png").read_bytes())
    assert stack.operations.preflight_retry(VIDEO, ["v-1"]).submittable


# ------------------------------------------------------------------ output navigation (28-30)


def _result(image=None, video=None, thumbnail=None):
    metadata = {}
    if video:
        metadata["video_primary_artifact"] = {
            "primary_path": str(video), "output_paths": [str(video)], "stage": "video_workflow",
            "artifact_type": "video", **({"thumbnail_path": str(thumbnail)} if thumbnail else {})}
    variants = [{"stage": "img2img", "path": str(image)}] if image else []
    return {"success": True, "variants": variants, "metadata": metadata}


def test_review_outputs_resolve_in_selection_order_and_report_what_is_unavailable(stack, tmp_path):
    outs = [image_file(tmp_path / "out" / f"o{i}.png", i) for i in range(4)]
    admit(stack, [review_njr(f"o-{i}", "rev", source_count=4) for i in range(4)])
    settle_fifo(stack, results={i: _result(image=outs[i]) for i in range(4)})
    outs[1].unlink()
    outs[2].write_bytes(b"not an image")
    resolution = stack.operations.resolve_outputs(REVIEW, ["o-3", "o-0", "o-1", "o-2"])
    assert resolution.images == (str(outs[3]), str(outs[0]))  # deterministic: selection order
    assert {(j, reason) for j, _, reason in resolution.unavailable} == {
        ("o-1", "missing or moved"), ("o-2", "not a readable image")}
    assert "missing or unreadable" in resolution.messages[0]


def test_video_outputs_use_existing_artifact_paths_and_a_thumbnail_is_an_image_not_a_video(stack, tmp_path):
    clip = tmp_path / "clips" / "a.mp4"
    clip.parent.mkdir()
    clip.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    thumb = image_file(tmp_path / "clips" / "a.png")
    admit(stack, [video_njr(f"c-{i}", "vid", i, 2) for i in range(2)])
    settle_fifo(stack, results={0: _result(video=clip, thumbnail=thumb)})
    resolution = stack.operations.resolve_outputs(VIDEO, ["c-0", "c-1"])
    assert resolution.videos == (str(clip),) and resolution.images == (str(thumb),)
    assert resolution.folders == (str(clip.parent),)
    assert resolution.jobs_without_outputs == ("c-1",)
    assert "no recorded output" in resolution.messages[0]


def test_absent_evidence_gives_actionable_messages_instead_of_silent_success(stack):
    admit(stack, [review_njr("x-0", "rev", source_count=1)])
    resolution = stack.operations.resolve_outputs(REVIEW, ["x-0", "ghost"])
    assert not resolution.images and not resolution.videos
    assert resolution.jobs_without_outputs == ("x-0", "ghost") and resolution.messages


def test_an_image_jobs_thumbnail_is_not_offered_to_review_but_a_video_jobs_is(stack, tmp_path):
    image = image_file(tmp_path / "img" / "full.png", 1)
    small = image_file(tmp_path / "img" / "full_thumb.png", 2)
    admit(stack, [review_njr("t-0", "rev", source_count=1)])
    stack.queue.claim_next_job()
    stack.queue.mark_completed("t-0", {"success": True, "variants": [], "artifact": {
        "schema": "stablenew.artifact.v2.6", "stage": "img2img", "artifact_type": "image",
        "primary_path": str(image), "output_paths": [str(image)], "thumbnail_path": str(small)}})
    resolution = stack.operations.resolve_outputs(REVIEW, ["t-0"])
    assert resolution.images == (str(image),)  # the thumbnail of an image job is not a second output
