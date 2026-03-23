"""Manifest and history payload helpers for staged curation."""

from __future__ import annotations

from collections.abc import Mapping
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


def build_serialized_curation_source_metadata(
    candidate: CurationCandidate,
    event: SelectionEvent,
    *,
    source_stage: str | None = None,
    face_triage_tier: str | None = None,
) -> dict[str, Any]:
    source_decision = str(getattr(event, "decision", "") or "").strip() or None
    candidate_block = build_candidate_lineage_block(candidate, source_decision=source_decision)
    return {
        "curation_source_selection": {
            "candidate_id": candidate.candidate_id,
            "workflow_id": candidate.workflow_id,
            "root_candidate_id": candidate.root_candidate_id,
            "parent_candidate_id": candidate.parent_candidate_id,
            "decision": str(getattr(event, "decision", "") or ""),
            "face_triage_tier": str(face_triage_tier or ""),
            "source_stage": str(source_stage or candidate.stage or ""),
            "model_name": str(candidate.model_name or ""),
        },
        "curation_candidate": dict(candidate_block.get("curation") or {}),
        "curation_selection_event": build_selection_event_block(event),
    }


def build_review_chunk_lineage_block(
    source_metadata: Mapping[str, Any] | None,
    *,
    target_stage: str,
) -> dict[str, Any]:
    if not isinstance(source_metadata, Mapping):
        return {}

    selection_meta = source_metadata.get("curation_source_selection")
    candidate_meta = source_metadata.get("curation_candidate")
    selection_event = source_metadata.get("curation_selection_event")
    if not isinstance(selection_meta, Mapping):
        return {}

    payload: dict[str, Any] = {
        "curation_derived_stage": {
            "workflow_id": str(
                selection_meta.get("workflow_id")
                or (candidate_meta.get("workflow_id") if isinstance(candidate_meta, Mapping) else "")
                or ""
            ),
            "target_stage": str(target_stage or ""),
            "source_candidate_id": str(selection_meta.get("candidate_id") or ""),
            "source_decision": str(selection_meta.get("decision") or ""),
            "face_triage_tier": str(selection_meta.get("face_triage_tier") or ""),
        }
    }
    if isinstance(candidate_meta, Mapping):
        payload["curation"] = dict(candidate_meta)
    if isinstance(selection_event, Mapping):
        payload["selection_event"] = dict(selection_event)
    return payload
