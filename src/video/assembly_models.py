"""Typed models for stitched and interpolated assembled-video outputs.

PR-VIDEO-217: StableNew-owned post-video assembly contracts. These models sit
between canonical sequence/video artifacts and Movie Clips so post-video
assembly has one provenance-aware result surface.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal


AssemblySourceKind = Literal[
    "sequence",
    "video_bundle",
    "assembled_video",
    "manual_frames",
    "video_segments",
]


@dataclass(frozen=True)
class AssemblySegmentSource:
    """One source segment participating in stitched assembly."""

    segment_index: int
    segment_id: str
    primary_output_path: str | None
    output_paths: list[str] = field(default_factory=list)
    frame_paths: list[str] = field(default_factory=list)
    source_image_path: str | None = None
    manifest_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AssemblySegmentSource":
        return cls(
            segment_index=int(data.get("segment_index", 0)),
            segment_id=str(data.get("segment_id", "")),
            primary_output_path=data.get("primary_output_path"),
            output_paths=[str(item) for item in data.get("output_paths") or [] if item],
            frame_paths=[str(item) for item in data.get("frame_paths") or [] if item],
            source_image_path=data.get("source_image_path"),
            manifest_path=data.get("manifest_path"),
        )


@dataclass
class AssembledSequenceInput:
    """Canonical source bundle for post-video assembly."""

    source_kind: AssemblySourceKind
    source_id: str
    job_id: str | None = None
    manifest_path: str | None = None
    source_paths: list[str] = field(default_factory=list)
    frame_paths: list[str] = field(default_factory=list)
    segment_sources: list[AssemblySegmentSource] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_kind": self.source_kind,
            "source_id": self.source_id,
            "job_id": self.job_id,
            "manifest_path": self.manifest_path,
            "source_paths": list(self.source_paths),
            "frame_paths": list(self.frame_paths),
            "segment_sources": [segment.to_dict() for segment in self.segment_sources],
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AssembledSequenceInput":
        return cls(
            source_kind=data.get("source_kind", "manual_frames"),
            source_id=str(data.get("source_id", "")),
            job_id=data.get("job_id"),
            manifest_path=data.get("manifest_path"),
            source_paths=[str(item) for item in data.get("source_paths") or [] if item],
            frame_paths=[str(item) for item in data.get("frame_paths") or [] if item],
            segment_sources=[
                AssemblySegmentSource.from_dict(item)
                for item in data.get("segment_sources") or []
                if isinstance(item, dict)
            ],
            metadata=dict(data.get("metadata") or {}),
        )

    @classmethod
    def from_sequence_artifact(cls, data: dict[str, Any]) -> "AssembledSequenceInput":
        segment_sources = [
            AssemblySegmentSource.from_dict(item)
            for item in data.get("segment_provenance") or []
            if isinstance(item, dict)
        ]
        reserved = {
            "sequence_id",
            "job_id",
            "sequence_manifest_path",
            "all_output_paths",
            "all_frame_paths",
            "segment_provenance",
            "completed_segments",
            "total_segments",
            "is_complete",
            "assembled_video",
        }
        metadata = {key: value for key, value in data.items() if key not in reserved}
        return cls(
            source_kind="sequence",
            source_id=str(data.get("sequence_id") or data.get("job_id") or "sequence"),
            job_id=data.get("job_id"),
            manifest_path=data.get("sequence_manifest_path"),
            source_paths=[str(item) for item in data.get("all_output_paths") or [] if item],
            frame_paths=[str(item) for item in data.get("all_frame_paths") or [] if item],
            segment_sources=segment_sources,
            metadata=metadata,
        )

    @classmethod
    def from_video_artifact_bundle(
        cls,
        data: dict[str, Any],
        *,
        source_kind: AssemblySourceKind = "video_bundle",
    ) -> "AssembledSequenceInput":
        source_paths: list[str] = [str(item) for item in data.get("output_paths") or [] if item]
        if not source_paths and data.get("primary_path"):
            source_paths = [str(data.get("primary_path"))]
        reserved = {
            "stage",
            "backend_id",
            "artifact_type",
            "primary_path",
            "output_paths",
            "video_paths",
            "gif_paths",
            "frame_paths",
            "manifest_path",
            "manifest_paths",
            "thumbnail_path",
            "source_image_path",
            "count",
            "artifacts",
        }
        metadata = {key: value for key, value in data.items() if key not in reserved}
        return cls(
            source_kind=source_kind,
            source_id=str(data.get("stage") or data.get("primary_path") or "video_bundle"),
            manifest_path=data.get("manifest_path"),
            source_paths=source_paths,
            frame_paths=[str(item) for item in data.get("frame_paths") or [] if item],
            metadata=metadata,
        )

    @classmethod
    def from_paths(
        cls,
        paths: list[str | Path],
        *,
        source_kind: AssemblySourceKind,
        source_id: str = "manual",
    ) -> "AssembledSequenceInput":
        resolved_paths = [str(Path(item)) for item in paths if item]
        frame_paths = list(resolved_paths) if source_kind == "manual_frames" else []
        return cls(
            source_kind=source_kind,
            source_id=source_id,
            source_paths=resolved_paths,
            frame_paths=frame_paths,
        )

    def resolved_segment_output_paths(self) -> list[str]:
        if self.segment_sources:
            paths: list[str] = []
            for segment in sorted(self.segment_sources, key=lambda item: item.segment_index):
                if segment.primary_output_path:
                    paths.append(str(segment.primary_output_path))
                    continue
                for output_path in segment.output_paths:
                    if output_path:
                        paths.append(str(output_path))
                        break
            return paths
        return list(self.source_paths)

    def resolved_frame_paths(self) -> list[str]:
        if self.frame_paths:
            return list(self.frame_paths)
        if self.segment_sources:
            return [
                frame_path
                for segment in sorted(self.segment_sources, key=lambda item: item.segment_index)
                for frame_path in segment.frame_paths
                if frame_path
            ]
        return []

    def source_image_path(self) -> str | None:
        for segment in sorted(self.segment_sources, key=lambda item: item.segment_index):
            if segment.source_image_path:
                return str(segment.source_image_path)
        resolved_frames = self.resolved_frame_paths()
        if resolved_frames:
            return str(resolved_frames[0])
        return None


@dataclass
class StitchedOutput:
    """Canonical stitched-video output before optional interpolation."""

    primary_path: str | None
    output_paths: list[str] = field(default_factory=list)
    manifest_path: str | None = None
    source_segment_paths: list[str] = field(default_factory=list)
    artifact_bundle: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class InterpolatedOutput:
    """Interpolation provider output attached to an assembled video result."""

    provider_id: str
    applied: bool
    primary_path: str | None = None
    input_paths: list[str] = field(default_factory=list)
    output_paths: list[str] = field(default_factory=list)
    manifest_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ExportReadyOutputBundle:
    """Final export-ready artifact bundle emitted by StableNew assembly."""

    primary_path: str | None
    output_paths: list[str] = field(default_factory=list)
    manifest_path: str | None = None
    artifact_bundle: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AssemblyRequest:
    """Typed assembly request consumed by ``AssemblyService``."""

    source: AssembledSequenceInput
    output_dir: str | Path
    clip_name: str = ""
    fps: int = 24
    codec: str = "libx264"
    quality: str = "medium"
    mode: str = "sequence"
    duration_per_image: float = 3.0
    transition_duration: float = 0.5
    interpolation_enabled: bool = False
    interpolation_factor: int = 2
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.source is None:
            errors.append("source must be provided")
        if not str(self.output_dir).strip():
            errors.append("output_dir must be provided")
        if self.fps < 1:
            errors.append("fps must be >= 1")
        if self.mode not in ("sequence", "slideshow"):
            errors.append("mode must be 'sequence' or 'slideshow'")
        if self.interpolation_factor < 1:
            errors.append("interpolation_factor must be >= 1")
        return errors

    def export_settings_dict(self) -> dict[str, Any]:
        return {
            "fps": self.fps,
            "codec": self.codec,
            "quality": self.quality,
            "mode": self.mode,
            "duration_per_image": self.duration_per_image,
            "transition_duration": self.transition_duration,
            "interpolation_enabled": self.interpolation_enabled,
            "interpolation_factor": self.interpolation_factor,
        }


@dataclass
class AssembledVideoResult:
    """Final StableNew-owned assembled-video result."""

    success: bool
    source: AssembledSequenceInput | None = None
    export_settings: dict[str, Any] = field(default_factory=dict)
    stitched_output: StitchedOutput | None = None
    interpolated_output: InterpolatedOutput | None = None
    export_output: ExportReadyOutputBundle | None = None
    manifest_path: str | None = None
    clip_name: str = ""
    error: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @classmethod
    def failure(
        cls,
        reason: str,
        *,
        source: AssembledSequenceInput | None = None,
        clip_name: str = "",
        export_settings: dict[str, Any] | None = None,
    ) -> "AssembledVideoResult":
        return cls(
            success=False,
            source=source,
            clip_name=clip_name,
            export_settings=dict(export_settings or {}),
            error=reason,
        )

    @property
    def primary_path(self) -> str | None:
        if self.export_output and self.export_output.primary_path:
            return str(self.export_output.primary_path)
        if self.interpolated_output and self.interpolated_output.primary_path:
            return str(self.interpolated_output.primary_path)
        if self.stitched_output and self.stitched_output.primary_path:
            return str(self.stitched_output.primary_path)
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "clip_name": self.clip_name,
            "primary_path": self.primary_path,
            "manifest_path": self.manifest_path,
            "export_settings": dict(self.export_settings),
            "source": self.source.to_dict() if self.source else None,
            "stitched_output": self.stitched_output.to_dict() if self.stitched_output else None,
            "interpolated_output": (
                self.interpolated_output.to_dict() if self.interpolated_output else None
            ),
            "export_output": self.export_output.to_dict() if self.export_output else None,
            "error": self.error,
            "created_at": self.created_at,
        }