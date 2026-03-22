from __future__ import annotations

from src.curation.models import (
    CurationCandidate,
    CurationOutcome,
    CurationWorkflow,
    FaceTriageProfile,
    RefineProfile,
    SelectionEvent,
)


def test_curation_models_roundtrip() -> None:
    workflow = CurationWorkflow(
        workflow_id="wf-1",
        title="Scout Session",
        created_at="2026-03-21T21:00:00Z",
        status="draft",
        root_prompt_fingerprint="sha256:prompt",
        root_config_fingerprint="sha256:config",
        root_model="juggernautXL_ragnarokBy",
        notes="initial notes",
    )
    candidate = CurationCandidate(
        candidate_id="cand-1",
        workflow_id="wf-1",
        stage="scout",
        artifact_id="artifact-1",
        job_id="job-1",
        njr_id="njr-1",
        parent_candidate_id=None,
        root_candidate_id="cand-1",
        prompt_fingerprint="sha256:prompt",
        config_fingerprint="sha256:config",
        model_name="juggernautXL_ragnarokBy",
        selected=True,
    )
    event = SelectionEvent(
        event_id="sel-1",
        workflow_id="wf-1",
        candidate_id="cand-1",
        stage="scout",
        decision="advanced_to_refine",
        timestamp="2026-03-21T21:05:00Z",
        reason_tags=["good_composition"],
        notes="worth refining",
    )
    refine = RefineProfile(
        strength="medium",
        img2img_denoise=0.32,
        steps=18,
        sampler_name="DPM++ 2M",
        scheduler="Karras",
        override_model=None,
    )
    triage = FaceTriageProfile(
        tier="light",
        confidence=0.75,
        denoise=0.18,
        steps=7,
        mask_padding=32,
    )
    outcome = CurationOutcome(
        workflow_id="wf-1",
        candidate_id="cand-1",
        final_rating=4.5,
        final_reason_tags=["keeper", "good_face"],
        final_review_notes="best finalist",
        kept=True,
        exported=False,
    )

    assert CurationWorkflow.from_dict(workflow.to_dict()) == workflow
    assert CurationCandidate.from_dict(candidate.to_dict()) == candidate
    assert SelectionEvent.from_dict(event.to_dict()) == event
    assert RefineProfile.from_dict(refine.to_dict()) == refine
    assert FaceTriageProfile.from_dict(triage.to_dict()) == triage
    assert CurationOutcome.from_dict(outcome.to_dict()) == outcome
