from __future__ import annotations

from pathlib import Path

from src.curation.curation_workflow_builder import (
    CurationSourceSelection,
    CurationWorkflowBuilder,
)
from src.curation.models import CurationCandidate, CurationWorkflow, SelectionEvent
from src.learning.discovered_review_models import DiscoveredReviewItem
from src.pipeline.reprocess_builder import ReprocessSourceItem
from src.state.output_routing import OUTPUT_ROUTE_LEARNING


def _make_workflow() -> CurationWorkflow:
    return CurationWorkflow(
        workflow_id="curation:group-1",
        title="Group 1",
        created_at="2026-03-21T18:00:00Z",
        status="scout_complete",
        root_prompt_fingerprint="prompt-hash",
        root_config_fingerprint="config-hash",
        root_model="juggernautXL",
    )


def _make_candidate() -> CurationCandidate:
    return CurationCandidate(
        candidate_id="cand-1",
        workflow_id="curation:group-1",
        stage="scout",
        artifact_id="artifact-1",
        job_id="job-1",
        njr_id="njr-1",
        parent_candidate_id=None,
        root_candidate_id="cand-1",
        prompt_fingerprint="prompt-hash",
        config_fingerprint="config-hash",
        model_name="juggernautXL",
    )


def _make_event(decision: str) -> SelectionEvent:
    return SelectionEvent(
        event_id="evt-1",
        workflow_id="curation:group-1",
        candidate_id="cand-1",
        stage="scout",
        decision=decision,  # type: ignore[arg-type]
        timestamp="2026-03-21T18:05:00Z",
        actor="user",
    )


def _make_source_selection(
    tmp_path,
    *,
    decision: str,
    face_tier: str = "medium",
) -> CurationSourceSelection:
    candidate = _make_candidate()
    event = _make_event(decision)
    image_path = tmp_path / "fake.png"
    image_path.write_text("placeholder", encoding="utf-8")
    item = DiscoveredReviewItem(
        item_id="cand-1",
        artifact_path=str(image_path),
        stage="txt2img",
        model="juggernautXL",
        sampler="DPM++ 2M",
        scheduler="Karras",
        steps=30,
        cfg_scale=6.5,
        positive_prompt="prompt",
        negative_prompt="negative",
    )
    reprocess = ReprocessSourceItem(
        input_image_path=str(image_path),
        prompt="prompt",
        negative_prompt="negative",
        model="juggernautXL",
        vae="Automatic",
        config={
            "adetailer": {
                "adetailer_confidence": 0.69,
                "adetailer_denoise": 0.25,
                "adetailer_steps": 8,
            }
        },
        metadata={
            "curation_candidate": candidate,
            "curation_selection_event": event,
        },
    )
    return CurationSourceSelection(
        candidate=candidate,
        source_item=item,
        selection_event=event,
        reprocess_item=reprocess,
        face_triage_tier=face_tier,
    )


def test_face_triage_plan_applies_profile_and_learning_route(tmp_path) -> None:
    builder = CurationWorkflowBuilder()

    plan = builder.build_derived_stage_plan(
        workflow=_make_workflow(),
        target_stage="face_triage",
        selections=[_make_source_selection(tmp_path, decision="advanced_to_face_triage", face_tier="heavy")],
        fallback_config={"pipeline": {"batch_size": 1}},
        output_dir="output",
    )

    assert len(plan.jobs) == 1
    record = plan.jobs[0]
    assert record.start_stage == "adetailer"
    assert record.stage_chain[0].stage_type == "adetailer"
    assert record.config["pipeline"]["output_route"] == OUTPUT_ROUTE_LEARNING
    assert record.config["adetailer"]["adetailer_denoise"] == 0.34
    assert record.config["adetailer"]["adetailer_steps"] == 12
    assert record.extra_metadata["curation"]["candidate_id"] == "cand-1"
    assert record.extra_metadata["curation"]["source_decision"] == "advanced_to_face_triage"
    assert record.extra_metadata["curation_derived_stage"]["face_triage_tier"] == "heavy"
    assert record.extra_metadata["selection_event"]["decision"] == "advanced_to_face_triage"


def test_face_triage_plan_skips_candidates_with_skip_tier(tmp_path) -> None:
    builder = CurationWorkflowBuilder()

    plan = builder.build_derived_stage_plan(
        workflow=_make_workflow(),
        target_stage="face_triage",
        selections=[_make_source_selection(tmp_path, decision="advanced_to_face_triage", face_tier="skip")],
        fallback_config={},
        output_dir="output",
    )

    assert plan.jobs == []


def test_refine_plan_uses_img2img_stage(tmp_path) -> None:
    builder = CurationWorkflowBuilder()

    plan = builder.build_derived_stage_plan(
        workflow=_make_workflow(),
        target_stage="refine",
        selections=[_make_source_selection(tmp_path, decision="advanced_to_refine")],
        fallback_config={},
        output_dir="output",
    )

    assert len(plan.jobs) == 1
    record = plan.jobs[0]
    assert record.start_stage == "img2img"
    assert record.stage_chain[0].stage_type == "img2img"
    assert record.config["pipeline"]["output_route"] == OUTPUT_ROUTE_LEARNING
