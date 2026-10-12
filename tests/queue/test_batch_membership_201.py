"""PR-BATCH-OPS-201: pure membership, replay lineage, triage and aggregate-state contracts."""

from __future__ import annotations

import pytest

from src.pipeline.replay_njr_compiler import ReplayIntent, compile_replay_intent
from src.queue.batch_membership import (
    BATCH_SCHEMA,
    BatchKey,
    BatchKind,
    MembershipState,
    build_selected_retry_descriptor,
    replay_origin_of,
    resolve_batch_membership,
)
from src.queue.batch_projection import BatchAggregateState, StatusCounts, derive_aggregate_state
from src.queue.failure_triage import TriageCategory, bounded_message, triage_failure
from src.queue.job_history_store import INTERRUPTED_RESTART_ACTION_REQUIRED
from src.utils.error_envelope_v2 import UnifiedErrorEnvelope
from tests.helpers.batch_ops_201 import review_njr, video_njr
from tests.helpers.njr_factory import make_pipeline_njr


def _video(**overrides):
    descriptor = {
        "schema": BATCH_SCHEMA,
        "batch_id": "vid-1",
        "batch_kind": "video_workflow",
        "source_index": 0,
        "source_count": 3,
    }
    descriptor.update(overrides)
    return {"batch": descriptor}


# ------------------------------------------------------------------------------------------ membership (1-3)


def test_review_shape_resolves_with_separate_source_count():
    resolution = resolve_batch_membership(review_njr("j1", "rev-1", source_count=25).extra_metadata)
    membership = resolution.membership
    assert resolution.state is MembershipState.MEMBER and membership is not None
    assert membership.key == BatchKey(BatchKind.REVIEW, "rev-1")
    assert membership.source_index is None and membership.declared_source_count == 25


def test_video_shape_resolves_with_zero_based_index():
    membership = resolve_batch_membership(video_njr("j", "vid-1", 0, 25).extra_metadata).membership
    assert membership.key == BatchKey(BatchKind.VIDEO_WORKFLOW, "vid-1")
    assert (membership.source_index, membership.declared_source_count) == (0, 25)


def test_composite_identity_keeps_equal_ids_of_different_kinds_apart():
    review = resolve_batch_membership(review_njr("a", "same").extra_metadata).membership.key
    video = resolve_batch_membership(video_njr("b", "same", 0, 2).extra_metadata).membership.key
    assert review != video and review.batch_id == video.batch_id
    assert BatchKey.from_token(review.to_token()) == review
    assert BatchKey.from_token("nonsense") is None and BatchKey.from_token("review:") is None


@pytest.mark.parametrize(
    "metadata",
    [
        {},
        {"batch_id": "orphan"},  # a bare top-level id has no kind: never a batch
        {"review_batch": {"source_count": 3}},  # no id
        {"review_batch": "garbage"},
        {"batch": {"schema": "stablenew.batch.v0", "batch_id": "x", "batch_kind": "video_workflow"}},
        _video(batch_kind="pack_name"),  # unsupported kind
        _video(source_index=-1),
        _video(source_index=3),  # index must be below the declared count
        _video(source_count=0),
        _video(source_index=True),
        _video(batch_id="  "),
    ],
)
def test_records_without_a_valid_identity_stay_ordinary_jobs(metadata):
    resolution = resolve_batch_membership(metadata)
    assert resolution.state is MembershipState.UNGROUPED and resolution.membership is None


@pytest.mark.parametrize(
    "metadata",
    [
        {"review_batch": {"batch_id": "a", "source_count": 2}, "batch_id": "b"},
        {**_video(), "batch_id": "other"},
        {**_video(), "review_batch": {"batch_id": "vid-1", "source_count": 3}},
    ],
)
def test_conflicting_identifiers_are_ambiguous_never_merged(metadata):
    resolution = resolve_batch_membership(metadata)
    assert resolution.state is MembershipState.AMBIGUOUS and resolution.membership is None


def test_review_without_top_level_id_is_still_a_member():
    # The associated top-level id is optional; the descriptor alone is a valid identity.
    resolution = resolve_batch_membership(review_njr("j", "rev-9", top_level=False).extra_metadata)
    assert resolution.membership.key.batch_id == "rev-9"


# ------------------------------------------------------------------------------------- replay lineage (19-20)


def test_replay_never_inherits_active_review_membership_but_keeps_it_as_origin():
    parent = review_njr("parent", "rev-1")
    child = compile_replay_intent(ReplayIntent(parent), id_fn=lambda: "child")
    metadata = child.extra_metadata
    assert child.job_id == "child" and child.source.parent_job_id == "parent"
    assert resolve_batch_membership(metadata).state is MembershipState.UNGROUPED
    assert "review_batch" not in metadata and "batch_id" not in metadata
    origin = replay_origin_of(metadata)
    assert origin is not None and origin.parent_job_id == "parent"
    assert origin.key == BatchKey(BatchKind.REVIEW, "rev-1")
    # Unrelated provenance is preserved exactly.
    assert metadata["submission_source"] == "review_tab" and metadata["replay"] is True
    # The parent record itself is untouched.
    assert parent.extra_metadata["review_batch"]["batch_id"] == "rev-1"


def test_replay_never_inherits_active_video_membership():
    parent = video_njr("parent", "vid-1", 3, 5)
    child = compile_replay_intent(ReplayIntent(parent))
    assert resolve_batch_membership(child.extra_metadata).state is MembershipState.UNGROUPED
    assert replay_origin_of(child.extra_metadata).key == BatchKey(BatchKind.VIDEO_WORKFLOW, "vid-1")
    assert child.job_id != parent.job_id


def test_replay_of_ordinary_job_adds_no_origin_noise():
    child = compile_replay_intent(ReplayIntent(make_pipeline_njr(job_id="p")))
    assert replay_origin_of(child.extra_metadata) is None
    assert "replay_origin" not in child.extra_metadata


def test_replay_of_a_replay_keeps_the_nearest_known_origin():
    first = compile_replay_intent(ReplayIntent(video_njr("p", "vid-1", 0, 2)), id_fn=lambda: "c1")
    second = compile_replay_intent(ReplayIntent(first), id_fn=lambda: "c2")
    assert replay_origin_of(second.extra_metadata).key == BatchKey(BatchKind.VIDEO_WORKFLOW, "vid-1")
    assert second.source.parent_job_id == "c1"


def test_selected_retry_descriptor_is_a_new_versioned_membership_distinct_from_the_origin():
    parent = review_njr("p", "rev-1")
    descriptor = build_selected_retry_descriptor("ret-1", source_index=1, source_count=3)
    child = compile_replay_intent(ReplayIntent(parent, batch=descriptor))
    membership = resolve_batch_membership(child.extra_metadata).membership
    assert membership.key == BatchKey(BatchKind.SELECTED_RETRY, "ret-1")
    assert (membership.source_index, membership.declared_source_count) == (1, 3)
    assert replay_origin_of(child.extra_metadata).key == BatchKey(BatchKind.REVIEW, "rev-1")
    assert descriptor["schema"] == BATCH_SCHEMA


# ----------------------------------------------------------------------------------------- aggregate state (8)


@pytest.mark.parametrize(
    ("counts", "expected"),
    [
        (StatusCounts(queued=2, running=1), BatchAggregateState.ACTIVE),
        (StatusCounts(queued=3), BatchAggregateState.WAITING),
        (StatusCounts(completed=4), BatchAggregateState.COMPLETED),
        (StatusCounts(completed=3, failed=1), BatchAggregateState.COMPLETED_WITH_FAILURES),
        (StatusCounts(failed=2, cancelled=1), BatchAggregateState.FAILED),
        (StatusCounts(completed=2, cancelled=2), BatchAggregateState.COMPLETED_WITH_CANCELLATIONS),
        (StatusCounts(completed=1, failed=1, cancelled=1), BatchAggregateState.COMPLETED_WITH_FAILURES),
        (StatusCounts(cancelled=5), BatchAggregateState.CANCELLED),
    ],
)
def test_aggregate_state_is_a_pure_function_of_canonical_counts(counts, expected):
    assert derive_aggregate_state(counts) is expected


# ---------------------------------------------------------------------------------------------- triage (§6)


def _evidence(**fields):
    base = {"contract": "webui_failure_evidence/1", "stage": "txt2img"}
    base.update(fields)
    return {"metadata": {"failure_evidence": base}}


@pytest.mark.parametrize(
    ("evidence", "category", "ack"),
    [
        ({"error_code": "connection_error", "webui_unavailable": True},
         TriageCategory.PRE_DISPATCH_UNAVAILABLE, False),
        ({"identity_refused": True, "observed_identity": "unknown", "identity_gap": "no_evidence"},
         TriageCategory.READINESS_OR_IDENTITY, False),
        ({"recovery_classification": "true_ready_timeout"}, TriageCategory.READINESS_OR_IDENTITY, False),
        ({"error_code": "outcome_unknown"}, TriageCategory.OUTCOME_UNKNOWN, True),
        ({"request_may_have_executed": True}, TriageCategory.OUTCOME_UNKNOWN, True),
        ({"timeout": True}, TriageCategory.OUTCOME_UNKNOWN, True),
        ({"http_status": 422}, TriageCategory.HTTP_REJECTION, False),
        ({"http_status": 500, "crash_suspected": True}, TriageCategory.HTTP_REJECTION, True),
        ({"error_code": "invalid_model"}, TriageCategory.INVALID_CONFIGURATION, False),
        ({"error_code": "payload_validation_error"}, TriageCategory.INVALID_CONFIGURATION, False),
        ({"error_code": "unknown_error"}, TriageCategory.OTHER, False),
    ],
)
def test_typed_evidence_classifies_without_reading_message_text(evidence, category, ack):
    triage = triage_failure(error_message="boom", result=_evidence(**evidence))
    assert triage.category is category and triage.typed is True
    assert triage.acknowledgement_required is ack
    assert (triage.acknowledgement_text is not None) is ack
    assert triage.stage == "txt2img"


def test_message_keywords_never_decide_a_category():
    for text in ("CUDA out of memory", "connection refused", "read timed out", "HTTP 500"):
        triage = triage_failure(error_message=text)
        assert triage.category is TriageCategory.OTHER and triage.typed is False
        assert triage.dispatch_certainty == "untyped" and not triage.acknowledgement_required


def test_restart_interruption_is_outcome_unknown_and_needs_acknowledgement():
    envelope = UnifiedErrorEnvelope(
        error_type=INTERRUPTED_RESTART_ACTION_REQUIRED, subsystem="queue_recovery", severity="ERROR",
        message="StableNew exited while this job was running.", cause=None, stack="", job_id="j",
        stage=None, context={"generation_outcome": "ambiguous", "action_required": True},
    )
    triage = triage_failure(error_message=envelope.message, envelope=envelope)
    assert triage.category is TriageCategory.OUTCOME_UNKNOWN
    assert triage.acknowledgement_required and triage.action_required and triage.typed


@pytest.mark.parametrize(
    ("error_type", "category"),
    [
        ("SVDOutOfMemoryError", TriageCategory.RESOURCE_EXHAUSTION),
        ("ResourceLimitError", TriageCategory.RESOURCE_EXHAUSTION),
        ("SVDConfigError", TriageCategory.INVALID_CONFIGURATION),
        ("OperationNotSupportedError", TriageCategory.INVALID_CONFIGURATION),
        ("RuntimeError", TriageCategory.OTHER),
    ],
)
def test_envelope_exception_type_is_typed_evidence_for_non_webui_failures(error_type, category):
    envelope = {"error_type": error_type, "stage": "svd_native", "message": "x", "context": {}}
    triage = triage_failure(error_message="x", envelope=envelope)
    assert triage.category is category and triage.stage == "svd_native"


def test_failure_summary_is_bounded_and_single_line():
    huge = "first line " + "word " * 500 + "\nsecond line with a full prompt dump"
    triage = triage_failure(error_message=huge)
    assert "\n" not in triage.summary and len(triage.summary) <= 240
    assert bounded_message("a\n\n  b") == "a"
