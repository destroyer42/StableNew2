from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from src.video.continuity_models import normalize_continuity_link


STORY_PLAN_SCHEMA_V26 = "stablenew.story_plan.v2.6"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mapping_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _normalize_link(value: Any) -> dict[str, Any] | None:
    return normalize_continuity_link(value)


@dataclass
class AnchorPlan:
    anchor_id: str
    display_name: str
    source_image_path: str | None = None
    prompt: str = ""
    negative_prompt: str = ""
    workflow_id: str | None = None
    segment_length_frames: int | None = None
    overlap_frames: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "anchor_id": self.anchor_id,
            "display_name": self.display_name,
            "source_image_path": self.source_image_path,
            "prompt": self.prompt,
            "negative_prompt": self.negative_prompt,
            "workflow_id": self.workflow_id,
            "segment_length_frames": self.segment_length_frames,
            "overlap_frames": self.overlap_frames,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> AnchorPlan:
        payload = _mapping_dict(data)
        return cls(
            anchor_id=str(payload.get("anchor_id") or ""),
            display_name=str(payload.get("display_name") or payload.get("anchor_id") or ""),
            source_image_path=str(payload.get("source_image_path") or "").strip() or None,
            prompt=str(payload.get("prompt") or ""),
            negative_prompt=str(payload.get("negative_prompt") or ""),
            workflow_id=str(payload.get("workflow_id") or "").strip() or None,
            segment_length_frames=int(payload["segment_length_frames"])
            if payload.get("segment_length_frames") is not None
            else None,
            overlap_frames=int(payload["overlap_frames"])
            if payload.get("overlap_frames") is not None
            else None,
            metadata=_mapping_dict(payload.get("metadata")),
        )


@dataclass
class ShotPlan:
    shot_id: str
    display_name: str
    prompt: str
    negative_prompt: str = ""
    workflow_id: str | None = None
    total_segments: int = 1
    segment_length_frames: int = 0
    overlap_frames: int = 0
    carry_forward_policy: str = "none"
    anchors: list[AnchorPlan] = field(default_factory=list)
    continuity_link: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "shot_id": self.shot_id,
            "display_name": self.display_name,
            "prompt": self.prompt,
            "negative_prompt": self.negative_prompt,
            "workflow_id": self.workflow_id,
            "total_segments": self.total_segments,
            "segment_length_frames": self.segment_length_frames,
            "overlap_frames": self.overlap_frames,
            "carry_forward_policy": self.carry_forward_policy,
            "anchors": [anchor.to_dict() for anchor in self.anchors],
            "continuity_link": dict(self.continuity_link) if self.continuity_link else None,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> ShotPlan:
        payload = _mapping_dict(data)
        return cls(
            shot_id=str(payload.get("shot_id") or ""),
            display_name=str(payload.get("display_name") or payload.get("shot_id") or ""),
            prompt=str(payload.get("prompt") or ""),
            negative_prompt=str(payload.get("negative_prompt") or ""),
            workflow_id=str(payload.get("workflow_id") or "").strip() or None,
            total_segments=int(payload.get("total_segments") or 1),
            segment_length_frames=int(payload.get("segment_length_frames") or 0),
            overlap_frames=int(payload.get("overlap_frames") or 0),
            carry_forward_policy=str(payload.get("carry_forward_policy") or "none"),
            anchors=[AnchorPlan.from_dict(item) for item in list(payload.get("anchors") or [])],
            continuity_link=_normalize_link(payload.get("continuity_link")),
            metadata=_mapping_dict(payload.get("metadata")),
        )


@dataclass
class ScenePlan:
    scene_id: str
    display_name: str
    shots: list[ShotPlan] = field(default_factory=list)
    description: str = ""
    continuity_link: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scene_id": self.scene_id,
            "display_name": self.display_name,
            "shots": [shot.to_dict() for shot in self.shots],
            "description": self.description,
            "continuity_link": dict(self.continuity_link) if self.continuity_link else None,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> ScenePlan:
        payload = _mapping_dict(data)
        return cls(
            scene_id=str(payload.get("scene_id") or ""),
            display_name=str(payload.get("display_name") or payload.get("scene_id") or ""),
            shots=[ShotPlan.from_dict(item) for item in list(payload.get("shots") or [])],
            description=str(payload.get("description") or ""),
            continuity_link=_normalize_link(payload.get("continuity_link")),
            metadata=_mapping_dict(payload.get("metadata")),
        )


@dataclass
class StoryPlanSummary:
    plan_id: str
    display_name: str
    updated_at: str
    scene_count: int
    shot_count: int
    anchor_count: int
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "display_name": self.display_name,
            "updated_at": self.updated_at,
            "scene_count": self.scene_count,
            "shot_count": self.shot_count,
            "anchor_count": self.anchor_count,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> StoryPlanSummary:
        payload = _mapping_dict(data)
        return cls(
            plan_id=str(payload.get("plan_id") or ""),
            display_name=str(payload.get("display_name") or payload.get("plan_id") or ""),
            updated_at=str(payload.get("updated_at") or ""),
            scene_count=int(payload.get("scene_count") or 0),
            shot_count=int(payload.get("shot_count") or 0),
            anchor_count=int(payload.get("anchor_count") or 0),
            metadata=_mapping_dict(payload.get("metadata")),
        )


@dataclass
class StoryPlan:
    plan_id: str
    display_name: str
    scenes: list[ScenePlan] = field(default_factory=list)
    continuity_link: dict[str, Any] | None = None
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = STORY_PLAN_SCHEMA_V26

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "display_name": self.display_name,
            "scenes": [scene.to_dict() for scene in self.scenes],
            "continuity_link": dict(self.continuity_link) if self.continuity_link else None,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> StoryPlan:
        payload = _mapping_dict(data)
        return cls(
            plan_id=str(payload.get("plan_id") or ""),
            display_name=str(payload.get("display_name") or payload.get("plan_id") or ""),
            scenes=[ScenePlan.from_dict(item) for item in list(payload.get("scenes") or [])],
            continuity_link=_normalize_link(payload.get("continuity_link")),
            created_at=str(payload.get("created_at") or _now_iso()),
            updated_at=str(payload.get("updated_at") or _now_iso()),
            metadata=_mapping_dict(payload.get("metadata")),
            schema_version=str(payload.get("schema_version") or STORY_PLAN_SCHEMA_V26),
        )

    def summary(self) -> StoryPlanSummary:
        shot_count = sum(len(scene.shots) for scene in self.scenes)
        anchor_count = sum(len(shot.anchors) for scene in self.scenes for shot in scene.shots)
        return StoryPlanSummary(
            plan_id=self.plan_id,
            display_name=self.display_name or self.plan_id,
            updated_at=self.updated_at,
            scene_count=len(self.scenes),
            shot_count=shot_count,
            anchor_count=anchor_count,
            metadata=dict(self.metadata),
        )


__all__ = [
    "AnchorPlan",
    "ScenePlan",
    "ShotPlan",
    "StoryPlan",
    "StoryPlanSummary",
    "STORY_PLAN_SCHEMA_V26",
]