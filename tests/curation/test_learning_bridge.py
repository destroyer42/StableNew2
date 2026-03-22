from __future__ import annotations

from src.curation.learning_bridge import (
    CURATION_RECORD_KIND,
    CurationLearningBridge,
    CurationLearningContext,
)
from src.curation.models import CurationCandidate, SelectionEvent
from src.learning.discovered_review_models import DiscoveredReviewExperiment, DiscoveredReviewItem


def _make_candidate() -> CurationCandidate:
    return CurationCandidate(
        candidate_id="cand-1",
        workflow_id="curation:disc-1",
        stage="refine",
        artifact_id="artifact-1",
        job_id="job-1",
        njr_id="njr-1",
        parent_candidate_id="cand-0",
        root_candidate_id="cand-0",
        prompt_fingerprint="sha256:p",
        config_fingerprint="sha256:c",
        model_name="juggernautXL",
    )


def _make_item(*, rating: int = 0, source: str = "") -> DiscoveredReviewItem:
    extra_fields = {"source": source} if source else {}
    return DiscoveredReviewItem(
        item_id="cand-1",
        artifact_path="output/Pipeline/run-1/image.png",
        stage="refine",
        model="juggernautXL",
        sampler="DPM++ 2M",
        scheduler="Karras",
        steps=28,
        cfg_scale=6.5,
        width=1024,
        height=1536,
        positive_prompt="prompt text",
        negative_prompt="negative text",
        extra_fields=extra_fields,
        rating=rating,
    )


def _make_experiment(*, notes: str = "") -> DiscoveredReviewExperiment:
    return DiscoveredReviewExperiment(
        group_id="disc-1",
        display_name="Disc 1",
        stage="txt2img",
        prompt_hash="hash-1",
        notes=notes,
    )


def _make_event(*, decision: str = "advanced_to_upscale") -> SelectionEvent:
    return SelectionEvent(
        event_id="evt-1",
        workflow_id="curation:disc-1",
        candidate_id="cand-1",
        stage="refine",
        decision=decision,
        timestamp="2026-03-21T20:30:00Z",
        actor="user",
        reason_tags=["good_composition", "keeper"],
        notes="promising candidate",
    )


def test_build_learning_record_preserves_primary_knobs_and_reason_tags() -> None:
    record = CurationLearningBridge.build_learning_record(
        CurationLearningContext(
            workflow_id="curation:disc-1",
            candidate=_make_candidate(),
            experiment=_make_experiment(),
            item=_make_item(),
            event=_make_event(),
        )
    )

    assert record.metadata["record_kind"] == CURATION_RECORD_KIND
    assert record.primary_model == "juggernautXL"
    assert record.primary_sampler == "DPM++ 2M"
    assert record.primary_scheduler == "Karras"
    assert record.primary_steps == 28
    assert record.primary_cfg_scale == 6.5
    assert record.metadata["evidence_class"] == "observational"
    assert record.metadata["reason_tags"] == ["good_composition", "keeper"]
    assert record.metadata["lineage_depth"] == 1


def test_build_learning_record_uses_final_rating_when_present() -> None:
    record = CurationLearningBridge.build_learning_record(
        CurationLearningContext(
            workflow_id="curation:disc-1",
            candidate=_make_candidate(),
            experiment=_make_experiment(),
            item=_make_item(rating=5),
            event=_make_event(decision="not_advanced"),
        )
    )

    assert record.metadata["final_rating"] == 5.0
    assert record.metadata["user_rating"] == 5.0
    assert record.metadata["user_rating_source"] == "final_rating"


def test_determine_evidence_class_marks_controlled_sources() -> None:
    evidence_class = CurationLearningBridge.determine_evidence_class(
        _make_experiment(notes="Designed experiment import"),
        _make_item(source="learning_experiment"),
    )

    assert evidence_class == "controlled"
