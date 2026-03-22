from __future__ import annotations

from src.curation.models import CurationCandidate, CurationWorkflow, SelectionEvent
from src.curation.workflow_summary import (
    CURATION_REPLAY_DESCRIPTOR_SCHEMA,
    CURATION_WORKFLOW_SUMMARY_SCHEMA,
    build_candidate_replay_entry,
    build_curation_replay_descriptor_from_snapshot,
    build_workflow_summary,
)
from src.learning.discovered_review_models import DiscoveredReviewExperiment, DiscoveredReviewItem


def _workflow() -> CurationWorkflow:
    return CurationWorkflow(
        workflow_id="curation:disc-1",
        title="Disc 1",
        created_at="2026-03-21T21:00:00Z",
        status="scout_complete",
        root_prompt_fingerprint="hash-p",
        root_config_fingerprint="hash-c",
        root_model="juggernautXL",
    )


def _candidate(candidate_id: str = "item-1") -> CurationCandidate:
    return CurationCandidate(
        candidate_id=candidate_id,
        workflow_id="curation:disc-1",
        stage="scout",
        artifact_id=f"output/Pipeline/{candidate_id}.png",
        job_id="job-1",
        njr_id="njr-1",
        parent_candidate_id=None,
        root_candidate_id=candidate_id,
        prompt_fingerprint="hash-p",
        config_fingerprint=f"cfg:{candidate_id}",
        model_name="juggernautXL",
    )


def _item(item_id: str = "item-1", rating: int = 4) -> DiscoveredReviewItem:
    return DiscoveredReviewItem(
        item_id=item_id,
        artifact_path=f"output/Pipeline/{item_id}.png",
        stage="txt2img",
        model="juggernautXL",
        sampler="DPM++ 2M",
        scheduler="Karras",
        steps=30,
        cfg_scale=6.5,
        rating=rating,
        extra_fields={"face_triage_tier": "heavy"},
    )


def _event(candidate_id: str = "item-1") -> SelectionEvent:
    return SelectionEvent(
        event_id="evt-1",
        workflow_id="curation:disc-1",
        candidate_id=candidate_id,
        stage="scout",
        decision="advanced_to_face_triage",
        timestamp="2026-03-21T21:05:00Z",
        reason_tags=["bad_face"],
        notes="needs repair",
    )


def test_build_workflow_summary_counts_stages_decisions_and_tags() -> None:
    experiment = DiscoveredReviewExperiment(
        group_id="disc-1",
        display_name="Disc 1",
        stage="txt2img",
        prompt_hash="hash-p",
        items=[_item()],
        varying_fields=["cfg_scale"],
    )

    summary = build_workflow_summary(_workflow(), experiment, [_candidate()], [_event()])

    assert summary["schema"] == CURATION_WORKFLOW_SUMMARY_SCHEMA
    assert summary["candidate_count"] == 1
    assert summary["rated_count"] == 1
    assert summary["stage_counts"] == {"scout": 1}
    assert summary["decision_counts"] == {"advanced_to_face_triage": 1}
    assert summary["reason_tag_counts"] == {"bad_face": 1}


def test_build_candidate_replay_entry_includes_lineage_and_face_tier() -> None:
    entry = build_candidate_replay_entry(_candidate(), _item(), _event())

    assert entry["candidate_id"] == "item-1"
    assert entry["root_candidate_id"] == "item-1"
    assert entry["decision"] == "advanced_to_face_triage"
    assert entry["face_triage_tier"] == "heavy"


def test_build_curation_replay_descriptor_from_snapshot() -> None:
    payload = build_curation_replay_descriptor_from_snapshot(
        {
            "normalized_job": {
                "extra_metadata": {
                    "curation": {
                        "workflow_id": "curation:disc-1",
                        "candidate_id": "item-1",
                        "root_candidate_id": "item-1",
                        "parent_candidate_id": None,
                        "source_decision": "advanced_to_face_triage",
                    },
                    "curation_derived_stage": {
                        "workflow_id": "curation:disc-1",
                        "target_stage": "face_triage",
                        "source_candidate_id": "item-1",
                        "source_decision": "advanced_to_face_triage",
                        "face_triage_tier": "heavy",
                    },
                    "selection_event": {
                        "decision": "advanced_to_face_triage",
                    },
                }
            }
        }
    )

    assert payload["schema"] == CURATION_REPLAY_DESCRIPTOR_SCHEMA
    assert payload["workflow_id"] == "curation:disc-1"
    assert payload["candidate_id"] == "item-1"
    assert payload["target_stage"] == "face_triage"
    assert payload["face_triage_tier"] == "heavy"
