"""Manifest and history payload helpers for staged curation."""

from __future__ import annotations

from typing import Any

from .models import CurationCandidate, CurationOutcome, SelectionEvent

CURATION_SCHEMA = "stablenew.curation.v2.6"
SELECTION_EVENT_SCHEMA = "stablenew.selection_event.v2.6"
CURATION_OUTCOME_SCHEMA = "stablenew.curation_outcome.v2.6"


def build_candidate_lineage_block(
    candidate: CurationCandidate,
    *,
    source_decision: str | None = None,
) -> dict[str, Any]:
    return {
        "curation": {
            "schema": CURATION_SCHEMA,
            "workflow_id": candidate.workflow_id,
            "candidate_id": candidate.candidate_id,
            "stage": candidate.stage,
            "parent_candidate_id": candidate.parent_candidate_id,
            "root_candidate_id": candidate.root_candidate_id,
            "source_decision": source_decision,
            "prompt_fingerprint": candidate.prompt_fingerprint,
            "config_fingerprint": candidate.config_fingerprint,
            "model_name": candidate.model_name,
        }
    }


def build_selection_event_block(event: SelectionEvent) -> dict[str, Any]:
    payload = event.to_dict()
    payload["schema"] = SELECTION_EVENT_SCHEMA
    return payload


def build_curation_outcome_block(outcome: CurationOutcome) -> dict[str, Any]:
    return {
        "curation_outcome": {
            "schema": CURATION_OUTCOME_SCHEMA,
            **outcome.to_dict(),
        }
    }
