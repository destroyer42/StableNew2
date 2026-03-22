from __future__ import annotations

from src.curation.curation_manifest import (
    CURATION_OUTCOME_SCHEMA,
    CURATION_SCHEMA,
    SELECTION_EVENT_SCHEMA,
    build_candidate_lineage_block,
    build_curation_outcome_block,
    build_selection_event_block,
)
from src.curation.models import CurationCandidate, CurationOutcome, SelectionEvent


def test_build_candidate_lineage_block() -> None:
    candidate = CurationCandidate(
        candidate_id="cand-2",
        workflow_id="wf-2",
        stage="refine",
        artifact_id="artifact-2",
        job_id="job-2",
        njr_id="njr-2",
        parent_candidate_id="cand-1",
        root_candidate_id="cand-1",
        prompt_fingerprint="sha256:p",
        config_fingerprint="sha256:c",
        model_name="albedobaseXL_v31Large",
    )

    payload = build_candidate_lineage_block(candidate, source_decision="advanced_to_refine")

    assert payload["curation"]["schema"] == CURATION_SCHEMA
    assert payload["curation"]["candidate_id"] == "cand-2"
    assert payload["curation"]["parent_candidate_id"] == "cand-1"
    assert payload["curation"]["source_decision"] == "advanced_to_refine"


def test_build_selection_event_block() -> None:
    event = SelectionEvent(
        event_id="sel-2",
        workflow_id="wf-2",
        candidate_id="cand-2",
        stage="refine",
        decision="advanced_to_face_triage",
        timestamp="2026-03-21T21:10:00Z",
        reason_tags=["bad_face"],
        notes="send to face pass",
    )

    payload = build_selection_event_block(event)

    assert payload["schema"] == SELECTION_EVENT_SCHEMA
    assert payload["decision"] == "advanced_to_face_triage"
    assert payload["reason_tags"] == ["bad_face"]


def test_build_curation_outcome_block() -> None:
    outcome = CurationOutcome(
        workflow_id="wf-2",
        candidate_id="cand-2",
        final_rating=5.0,
        final_reason_tags=["keeper"],
        final_review_notes="top pick",
        kept=True,
        exported=True,
    )

    payload = build_curation_outcome_block(outcome)

    assert payload["curation_outcome"]["schema"] == CURATION_OUTCOME_SCHEMA
    assert payload["curation_outcome"]["candidate_id"] == "cand-2"
    assert payload["curation_outcome"]["kept"] is True
