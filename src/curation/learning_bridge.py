"""Bridge staged-curation decisions into canonical learning records."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.learning.learning_record import LearningRecord

from .models import CurationCandidate, SelectionEvent

CURATION_RECORD_KIND = "staged_curation_event"

SOFT_DECISION_SCORES: dict[str, float] = {
    "rejected_hard": 1.0,
    "not_advanced": 2.0,
    "advanced_to_refine": 3.2,
    "advanced_to_face_triage": 3.5,
    "advanced_to_finalist": 4.0,
    "advanced_to_upscale": 4.3,
    "curated_final": 5.0,
}

_LINEAGE_DEPTH_BY_STAGE: dict[str, int] = {
    "scout": 0,
    "refine": 1,
    "face_triage": 2,
    "upscale": 3,
    "final": 4,
}


@dataclass(slots=True)
class CurationLearningContext:
    workflow_id: str
    candidate: CurationCandidate
    experiment: Any
    item: Any
    event: SelectionEvent


class CurationLearningBridge:
    """Translate staged-curation decisions into structured learning records."""

    @classmethod
    def determine_evidence_class(cls, experiment: Any, item: Any) -> str:
        extra = dict(getattr(item, "extra_fields", {}) or {})
        source = str(extra.get("source") or "").strip().lower()
        notes = str(getattr(experiment, "notes", "") or "").strip().lower()
        if source in {"learning_experiment", "designed_experiment", "controlled"}:
            return "controlled"
        if "designed experiment" in notes or "controlled" in notes:
            return "controlled"
        return "observational"

    @classmethod
    def decision_score(cls, decision: str, *, final_rating: float | None = None) -> float:
        if final_rating is not None:
            try:
                rating_value = float(final_rating)
                if 1.0 <= rating_value <= 5.0:
                    return rating_value
            except (TypeError, ValueError):
                pass
        return SOFT_DECISION_SCORES.get(str(decision or "not_advanced"), 2.0)

    @classmethod
    def lineage_depth(cls, candidate: CurationCandidate) -> int:
        return _LINEAGE_DEPTH_BY_STAGE.get(str(candidate.stage or "scout"), 0)

    @classmethod
    def build_learning_record(cls, context: CurationLearningContext) -> LearningRecord:
        item = context.item
        event = context.event
        candidate = context.candidate
        experiment = context.experiment
        item_rating = getattr(item, "rating", 0)
        final_rating = float(item_rating) if int(item_rating or 0) > 0 else None
        user_rating = cls.decision_score(event.decision, final_rating=final_rating)
        evidence_class = cls.determine_evidence_class(experiment, item)
        stage_value = str(getattr(item, "stage", "") or candidate.stage or "txt2img")
        metadata = {
            "record_kind": CURATION_RECORD_KIND,
            "experiment_name": context.workflow_id,
            "variable_under_test": "staged_curation_decision",
            "variant_value": str(event.decision or ""),
            "user_rating": user_rating,
            "user_rating_source": "final_rating" if final_rating is not None else "soft_decision_score",
            "final_rating": final_rating,
            "advancement_score": SOFT_DECISION_SCORES.get(str(event.decision or ""), user_rating),
            "advancement_decision": str(event.decision or ""),
            "selection_reason_tags": list(getattr(event, "reason_tags", []) or []),
            "reason_tags": list(getattr(event, "reason_tags", []) or []),
            "user_notes": str(getattr(event, "notes", "") or ""),
            "stage": stage_value,
            "model": str(getattr(item, "model", "") or getattr(candidate, "model_name", "") or ""),
            "image_path": str(getattr(item, "artifact_path", "") or ""),
            "evidence_class": evidence_class,
            "controlled_evidence": evidence_class == "controlled",
            "observational_evidence": evidence_class == "observational",
            "lineage_depth": cls.lineage_depth(candidate),
            "curation_workflow_id": context.workflow_id,
            "curation_candidate_id": candidate.candidate_id,
            "curation_root_candidate_id": candidate.root_candidate_id,
            "curation_parent_candidate_id": candidate.parent_candidate_id,
            "curation_stage": str(candidate.stage or ""),
            "curation_prompt_hash": str(getattr(experiment, "prompt_hash", "") or ""),
        }
        primary_config = {
            "model": str(getattr(item, "model", "") or getattr(candidate, "model_name", "") or ""),
            "sampler": str(getattr(item, "sampler", "") or ""),
            "scheduler": str(getattr(item, "scheduler", "") or ""),
            "steps": int(getattr(item, "steps", 0) or 0),
            "cfg_scale": float(getattr(item, "cfg_scale", 0.0) or 0.0),
        }
        return LearningRecord.from_pipeline_context(
            base_config={
                "stage": stage_value,
                "model": primary_config["model"],
                "prompt": str(getattr(item, "positive_prompt", "") or ""),
                "negative_prompt": str(getattr(item, "negative_prompt", "") or ""),
                "width": int(getattr(item, "width", 0) or 0),
                "height": int(getattr(item, "height", 0) or 0),
            },
            variant_configs=[
                {
                    **primary_config,
                    "decision": str(event.decision or ""),
                    "reason_tags": list(getattr(event, "reason_tags", []) or []),
                    "candidate_stage": str(candidate.stage or ""),
                    "lineage_depth": cls.lineage_depth(candidate),
                }
            ],
            randomizer_mode="staged_curation",
            randomizer_plan_size=1,
            extract_primary=lambda cfg: {
                "model": cfg.get("model"),
                "sampler": cfg.get("sampler"),
                "scheduler": cfg.get("scheduler"),
                "steps": cfg.get("steps"),
                "cfg_scale": cfg.get("cfg_scale"),
            },
            metadata=metadata,
        )
