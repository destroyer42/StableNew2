"""Sequence and segment planning models for long-form video generation.

PR-VIDEO-216: First-class StableNew-owned sequence layer. One NJR-backed
workflow-video job can carry sequence intent, which the runner executes
deterministically segment by segment.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

# How a segment sources its anchor image from prior segments.
CarryForwardPolicy = Literal["first_frame", "last_frame", "provided", "none"]


@dataclass(frozen=True)
class VideoSegmentPlan:
    """Deterministic plan for one video segment within a sequence.

    Immutable and serializable. The planner produces these; the runner executes them.
    The ``segment_id`` is deterministic: same sequence_id + index always yields
    the same id, enabling replay.
    """

    segment_index: int
    segment_id: str
    source_image_path: str | None
    carry_forward_policy: CarryForwardPolicy
    overlap_frames: int
    segment_length_frames: int
    prompt: str
    negative_prompt: str
    workflow_id: str | None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VideoSegmentPlan":
        return cls(
            segment_index=int(data.get("segment_index", 0)),
            segment_id=str(data.get("segment_id", "")),
            source_image_path=data.get("source_image_path"),
            carry_forward_policy=data.get("carry_forward_policy", "none"),
            overlap_frames=int(data.get("overlap_frames", 0)),
            segment_length_frames=int(data.get("segment_length_frames", 0)),
            prompt=str(data.get("prompt", "")),
            negative_prompt=str(data.get("negative_prompt", "")),
            workflow_id=data.get("workflow_id"),
            extra=dict(data.get("extra") or {}),
        )


@dataclass
class VideoSequenceJob:
    """Sequence intent attached to an NJR workflow-video job.

    Describes all segments at planning time, before execution begins.
    Serializable so that sequence plans can be included in history and replays.
    """

    sequence_id: str
    job_id: str
    workflow_id: str
    total_segments: int
    segment_length_frames: int
    overlap_frames: int
    carry_forward_policy: CarryForwardPolicy
    base_source_image_path: str | None
    base_prompt: str
    base_negative_prompt: str
    per_segment_overrides: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VideoSequenceJob":
        return cls(
            sequence_id=str(data.get("sequence_id", "")),
            job_id=str(data.get("job_id", "")),
            workflow_id=str(data.get("workflow_id", "")),
            total_segments=int(data.get("total_segments", 1)),
            segment_length_frames=int(data.get("segment_length_frames", 0)),
            overlap_frames=int(data.get("overlap_frames", 0)),
            carry_forward_policy=data.get("carry_forward_policy", "none"),
            base_source_image_path=data.get("base_source_image_path"),
            base_prompt=str(data.get("base_prompt", "")),
            base_negative_prompt=str(data.get("base_negative_prompt", "")),
            per_segment_overrides=list(data.get("per_segment_overrides") or []),
        )


@dataclass(frozen=True)
class SegmentProvenanceRecord:
    """Per-segment provenance record, stamped after a segment completes."""

    sequence_id: str
    job_id: str
    segment_index: int
    segment_id: str
    source_image_path: str | None
    primary_output_path: str | None
    manifest_path: str | None
    output_paths: list[str] = field(default_factory=list)
    frame_paths: list[str] = field(default_factory=list)
    carry_forward_policy: CarryForwardPolicy = "none"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class VideoSequenceResult:
    """Aggregated result from executing all segments in a sequence.

    Mutated by the runner as each segment completes.
    """

    sequence_id: str
    job_id: str
    total_segments: int
    completed_segments: int = 0
    segment_provenance: list[SegmentProvenanceRecord] = field(default_factory=list)
    sequence_manifest_path: str | None = None
    all_output_paths: list[str] = field(default_factory=list)
    all_frame_paths: list[str] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        return self.completed_segments >= self.total_segments

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence_id": self.sequence_id,
            "job_id": self.job_id,
            "total_segments": self.total_segments,
            "completed_segments": self.completed_segments,
            "segment_provenance": [p.to_dict() for p in self.segment_provenance],
            "sequence_manifest_path": self.sequence_manifest_path,
            "all_output_paths": list(self.all_output_paths),
            "all_frame_paths": list(self.all_frame_paths),
            "is_complete": self.is_complete,
        }
