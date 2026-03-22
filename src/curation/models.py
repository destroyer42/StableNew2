"""Canonical staged-curation data models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

CurationWorkflowStatus = Literal[
    "draft",
    "scout_running",
    "scout_complete",
    "refine_running",
    "refine_complete",
    "face_triage_running",
    "face_triage_complete",
    "upscale_running",
    "complete",
    "cancelled",
]

CandidateStage = Literal["scout", "refine", "face_triage", "upscale", "final"]

SelectionDecision = Literal[
    "rejected_hard",
    "not_advanced",
    "advanced_to_refine",
    "advanced_to_face_triage",
    "advanced_to_finalist",
    "advanced_to_upscale",
    "curated_final",
]

RefineStrength = Literal["light", "medium", "heavy"]

FaceTriageTier = Literal["skip", "light", "medium", "heavy"]


@dataclass(slots=True)
class CurationWorkflow:
    workflow_id: str
    title: str
    created_at: str
    status: CurationWorkflowStatus
    root_prompt_fingerprint: str
    root_config_fingerprint: str
    root_model: str
    notes: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "CurationWorkflow":
        return cls(
            workflow_id=str(payload.get("workflow_id") or ""),
            title=str(payload.get("title") or ""),
            created_at=str(payload.get("created_at") or ""),
            status=str(payload.get("status") or "draft"),  # type: ignore[arg-type]
            root_prompt_fingerprint=str(payload.get("root_prompt_fingerprint") or ""),
            root_config_fingerprint=str(payload.get("root_config_fingerprint") or ""),
            root_model=str(payload.get("root_model") or ""),
            notes=str(payload["notes"]) if payload.get("notes") is not None else None,
        )


@dataclass(slots=True)
class CurationCandidate:
    candidate_id: str
    workflow_id: str
    stage: CandidateStage
    artifact_id: str
    job_id: str
    njr_id: str
    parent_candidate_id: str | None
    root_candidate_id: str
    prompt_fingerprint: str
    config_fingerprint: str
    model_name: str
    selected: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "CurationCandidate":
        return cls(
            candidate_id=str(payload.get("candidate_id") or ""),
            workflow_id=str(payload.get("workflow_id") or ""),
            stage=str(payload.get("stage") or "scout"),  # type: ignore[arg-type]
            artifact_id=str(payload.get("artifact_id") or ""),
            job_id=str(payload.get("job_id") or ""),
            njr_id=str(payload.get("njr_id") or ""),
            parent_candidate_id=(
                str(payload["parent_candidate_id"])
                if payload.get("parent_candidate_id") is not None
                else None
            ),
            root_candidate_id=str(payload.get("root_candidate_id") or ""),
            prompt_fingerprint=str(payload.get("prompt_fingerprint") or ""),
            config_fingerprint=str(payload.get("config_fingerprint") or ""),
            model_name=str(payload.get("model_name") or ""),
            selected=bool(payload.get("selected", False)),
        )


@dataclass(slots=True)
class SelectionEvent:
    event_id: str
    workflow_id: str
    candidate_id: str
    stage: str
    decision: SelectionDecision
    timestamp: str
    actor: str = "user"
    reason_tags: list[str] = field(default_factory=list)
    notes: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "SelectionEvent":
        return cls(
            event_id=str(payload.get("event_id") or ""),
            workflow_id=str(payload.get("workflow_id") or ""),
            candidate_id=str(payload.get("candidate_id") or ""),
            stage=str(payload.get("stage") or ""),
            decision=str(payload.get("decision") or "not_advanced"),  # type: ignore[arg-type]
            timestamp=str(payload.get("timestamp") or ""),
            actor=str(payload.get("actor") or "user"),
            reason_tags=[str(item) for item in list(payload.get("reason_tags") or [])],
            notes=str(payload["notes"]) if payload.get("notes") is not None else None,
        )


@dataclass(slots=True)
class RefineProfile:
    strength: RefineStrength
    img2img_denoise: float
    steps: int
    sampler_name: str
    scheduler: str
    override_model: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "RefineProfile":
        return cls(
            strength=str(payload.get("strength") or "light"),  # type: ignore[arg-type]
            img2img_denoise=float(payload.get("img2img_denoise") or 0.0),
            steps=int(payload.get("steps") or 0),
            sampler_name=str(payload.get("sampler_name") or ""),
            scheduler=str(payload.get("scheduler") or ""),
            override_model=str(payload["override_model"]) if payload.get("override_model") is not None else None,
        )


@dataclass(slots=True)
class FaceTriageProfile:
    tier: FaceTriageTier
    confidence: float
    denoise: float
    steps: int
    mask_padding: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "FaceTriageProfile":
        return cls(
            tier=str(payload.get("tier") or "skip"),  # type: ignore[arg-type]
            confidence=float(payload.get("confidence") or 0.0),
            denoise=float(payload.get("denoise") or 0.0),
            steps=int(payload.get("steps") or 0),
            mask_padding=int(payload.get("mask_padding") or 0),
        )


@dataclass(slots=True)
class CurationOutcome:
    workflow_id: str
    candidate_id: str
    final_rating: float | None
    final_reason_tags: list[str] = field(default_factory=list)
    final_review_notes: str | None = None
    kept: bool = False
    exported: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "CurationOutcome":
        rating = payload.get("final_rating")
        return cls(
            workflow_id=str(payload.get("workflow_id") or ""),
            candidate_id=str(payload.get("candidate_id") or ""),
            final_rating=float(rating) if rating is not None else None,
            final_reason_tags=[str(item) for item in list(payload.get("final_reason_tags") or [])],
            final_review_notes=(
                str(payload["final_review_notes"])
                if payload.get("final_review_notes") is not None
                else None
            ),
            kept=bool(payload.get("kept", False)),
            exported=bool(payload.get("exported", False)),
        )
