"""Workflow summary and replay helpers for staged curation."""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping

from .models import CurationCandidate, CurationWorkflow, SelectionEvent

CURATION_WORKFLOW_SUMMARY_SCHEMA = "stablenew.curation_workflow_summary.v2.6"
CURATION_REPLAY_DESCRIPTOR_SCHEMA = "stablenew.curation_replay_descriptor.v2.6"


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def build_candidate_replay_entry(
    candidate: CurationCandidate,
    item: Any | None,
    latest_event: SelectionEvent | None,
) -> dict[str, Any]:
    item_data = item
    extra_fields = dict(getattr(item_data, "extra_fields", {}) or {}) if item_data is not None else {}
    artifact_path = str(getattr(item_data, "artifact_path", "") or candidate.artifact_id or "")
    return {
        "candidate_id": candidate.candidate_id,
        "workflow_id": candidate.workflow_id,
        "stage": str(candidate.stage or ""),
        "root_candidate_id": str(candidate.root_candidate_id or ""),
        "parent_candidate_id": candidate.parent_candidate_id,
        "artifact_path": artifact_path,
        "model": str(getattr(item_data, "model", "") or candidate.model_name or ""),
        "decision": str(getattr(latest_event, "decision", "") or ""),
        "reason_tags": list(getattr(latest_event, "reason_tags", []) or []),
        "rating": _safe_int(getattr(item_data, "rating", 0) if item_data is not None else 0, 0),
        "face_triage_tier": str(extra_fields.get("face_triage_tier") or ""),
    }


def build_workflow_summary(
    workflow: CurationWorkflow,
    experiment: Any,
    candidates: list[CurationCandidate],
    selection_events: list[SelectionEvent],
) -> dict[str, Any]:
    item_by_id = {
        str(getattr(item, "item_id", "") or ""): item
        for item in list(getattr(experiment, "items", []) or [])
    }
    latest_events: dict[str, SelectionEvent] = {}
    for event in selection_events:
        latest_events[str(event.candidate_id or "")] = event

    stage_counts: Counter[str] = Counter()
    decision_counts: Counter[str] = Counter()
    reason_tag_counts: Counter[str] = Counter()
    rating_counts: Counter[str] = Counter()
    kept_count = 0
    rated_count = 0
    candidate_summaries: list[dict[str, Any]] = []
    latest_timestamp = ""

    for candidate in candidates:
        stage_counts[str(candidate.stage or "unknown")] += 1
        item = item_by_id.get(candidate.candidate_id)
        latest = latest_events.get(candidate.candidate_id)
        if latest is not None:
            decision = str(latest.decision or "")
            if decision:
                decision_counts[decision] += 1
                if decision == "curated_final":
                    kept_count += 1
            for tag in list(getattr(latest, "reason_tags", []) or []):
                clean = str(tag or "").strip()
                if clean:
                    reason_tag_counts[clean] += 1
            latest_timestamp = max(latest_timestamp, str(getattr(latest, "timestamp", "") or ""))
        rating_value = _safe_int(getattr(item, "rating", 0) if item is not None else 0, 0)
        if rating_value > 0:
            rated_count += 1
            rating_counts[str(rating_value)] += 1
        candidate_summaries.append(build_candidate_replay_entry(candidate, item, latest))

    return {
        "schema": CURATION_WORKFLOW_SUMMARY_SCHEMA,
        "workflow_id": workflow.workflow_id,
        "title": workflow.title,
        "status": str(getattr(experiment, "status", "") or workflow.status or ""),
        "created_at": workflow.created_at,
        "latest_event_at": latest_timestamp or None,
        "root_model": workflow.root_model,
        "prompt_hash": str(getattr(experiment, "prompt_hash", "") or workflow.root_prompt_fingerprint or ""),
        "varying_fields": list(getattr(experiment, "varying_fields", []) or []),
        "candidate_count": len(candidates),
        "selection_event_count": len(selection_events),
        "rated_count": rated_count,
        "kept_count": kept_count,
        "stage_counts": dict(stage_counts),
        "decision_counts": dict(decision_counts),
        "reason_tag_counts": dict(reason_tag_counts),
        "rating_counts": dict(rating_counts),
        "candidates": candidate_summaries,
    }


def build_curation_replay_descriptor_from_snapshot(
    njr_snapshot: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(njr_snapshot, Mapping):
        return {}
    snapshot = dict(njr_snapshot)
    normalized = snapshot.get("normalized_job")
    if isinstance(normalized, Mapping):
        snapshot = dict(normalized)
    extra_metadata = snapshot.get("extra_metadata")
    if not isinstance(extra_metadata, Mapping):
        return {}

    curation = extra_metadata.get("curation")
    derived_stage = extra_metadata.get("curation_derived_stage")
    selection_event = extra_metadata.get("selection_event")
    if not isinstance(curation, Mapping) and not isinstance(derived_stage, Mapping):
        return {}

    payload: dict[str, Any] = {
        "schema": CURATION_REPLAY_DESCRIPTOR_SCHEMA,
        "workflow_id": "",
        "candidate_id": "",
        "root_candidate_id": "",
        "parent_candidate_id": None,
        "source_decision": "",
        "target_stage": "",
        "selection_event": dict(selection_event) if isinstance(selection_event, Mapping) else {},
    }
    if isinstance(curation, Mapping):
        payload.update(
            {
                "workflow_id": str(
                    curation.get("workflow_id")
                    or payload["workflow_id"]
                    or ""
                ),
                "candidate_id": str(curation.get("candidate_id") or ""),
                "root_candidate_id": str(curation.get("root_candidate_id") or ""),
                "parent_candidate_id": curation.get("parent_candidate_id"),
                "source_decision": str(curation.get("source_decision") or ""),
                "stage": str(curation.get("stage") or ""),
            }
        )
    if isinstance(derived_stage, Mapping):
        payload.update(
            {
                "workflow_id": str(derived_stage.get("workflow_id") or payload["workflow_id"] or ""),
                "candidate_id": str(derived_stage.get("source_candidate_id") or payload["candidate_id"] or ""),
                "target_stage": str(derived_stage.get("target_stage") or ""),
                "source_decision": str(derived_stage.get("source_decision") or payload["source_decision"] or ""),
                "face_triage_tier": str(derived_stage.get("face_triage_tier") or ""),
            }
        )
    return payload
