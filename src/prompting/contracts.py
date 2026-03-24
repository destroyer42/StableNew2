from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


RecommendationPriority = Literal["low", "medium", "high"]
StagePolicyDecisionAction = Literal["applied", "preserved", "recommended"]


@dataclass(frozen=True, slots=True)
class PromptSourceContext:
    prompt_source: str = ""
    prompt_pack_id: str = ""
    prompt_pack_row_index: int | None = None
    run_mode: str = ""
    source: str = ""
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt_source": self.prompt_source,
            "prompt_pack_id": self.prompt_pack_id,
            "prompt_pack_row_index": self.prompt_pack_row_index,
            "run_mode": self.run_mode,
            "source": self.source,
            "tags": list(self.tags),
        }


@dataclass(frozen=True, slots=True)
class PromptContext:
    stage: str
    pipeline_name: str
    positive_chunk_count: int
    negative_chunk_count: int
    positive_bucket_counts: dict[str, int] = field(default_factory=dict)
    negative_bucket_counts: dict[str, int] = field(default_factory=dict)
    loras: list[dict[str, Any]] = field(default_factory=list)
    embeddings: list[dict[str, Any]] = field(default_factory=list)
    source: PromptSourceContext = field(default_factory=PromptSourceContext)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "pipeline_name": self.pipeline_name,
            "chunk_counts": {
                "positive": self.positive_chunk_count,
                "negative": self.negative_chunk_count,
            },
            "bucket_counts": {
                "positive": dict(self.positive_bucket_counts),
                "negative": dict(self.negative_bucket_counts),
            },
            "loras": [dict(item) for item in self.loras],
            "embeddings": [dict(item) for item in self.embeddings],
            "prompt_source": self.source.to_dict(),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True, slots=True)
class PromptIntentBundle:
    intent_band: str
    shot_type: str
    style_mode: str
    requested_pose: str
    wants_face_detail: bool
    wants_full_body: bool
    wants_portrait: bool
    has_people_tokens: bool
    has_lora_tokens: bool
    sensitive: bool
    sensitivity_reasons: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent_band": self.intent_band,
            "shot_type": self.shot_type,
            "style_mode": self.style_mode,
            "requested_pose": self.requested_pose,
            "wants_face_detail": self.wants_face_detail,
            "wants_full_body": self.wants_full_body,
            "wants_portrait": self.wants_portrait,
            "has_people_tokens": self.has_people_tokens,
            "has_lora_tokens": self.has_lora_tokens,
            "sensitive": self.sensitive,
            "sensitivity_reasons": list(self.sensitivity_reasons),
            "conflicts": list(self.conflicts),
        }


@dataclass(frozen=True, slots=True)
class PromptRecommendation:
    recommendation_id: str
    category: str
    priority: RecommendationPriority
    target: str
    action: str
    rationale: str
    suggested_settings: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "recommendation_id": self.recommendation_id,
            "category": self.category,
            "priority": self.priority,
            "target": self.target,
            "action": self.action,
            "rationale": self.rationale,
            "suggested_settings": dict(self.suggested_settings),
        }


@dataclass(frozen=True, slots=True)
class StagePolicyDecision:
    key: str
    value: Any
    action: StagePolicyDecisionAction
    rationale: str
    source_state: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "value": self.value,
            "action": self.action,
            "rationale": self.rationale,
            "source_state": self.source_state,
        }


@dataclass(frozen=True, slots=True)
class StagePolicyBundle:
    stage: str
    mode: str
    applied_settings: dict[str, Any] = field(default_factory=dict)
    applied_decisions: list[StagePolicyDecision] = field(default_factory=list)
    preserved_decisions: list[StagePolicyDecision] = field(default_factory=list)
    recommended_decisions: list[StagePolicyDecision] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "mode": self.mode,
            "applied_settings": dict(self.applied_settings),
            "applied_decisions": [item.to_dict() for item in self.applied_decisions],
            "preserved_decisions": [item.to_dict() for item in self.preserved_decisions],
            "recommended_decisions": [item.to_dict() for item in self.recommended_decisions],
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True, slots=True)
class PromptOptimizerAnalysisBundle:
    stage: str
    mode: str
    context: PromptContext
    intent: PromptIntentBundle
    recommendations: list[PromptRecommendation] = field(default_factory=list)
    stage_policy: StagePolicyBundle | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "mode": self.mode,
            "context": self.context.to_dict(),
            "intent": self.intent.to_dict(),
            "recommendations": [item.to_dict() for item in self.recommendations],
            "stage_policy": self.stage_policy.to_dict() if self.stage_policy is not None else None,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }
