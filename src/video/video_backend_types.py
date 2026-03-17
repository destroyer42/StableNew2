from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from src.pipeline.artifact_contract import (
    ARTIFACT_SCHEMA_VERSION,
    build_artifact_record,
    canonicalize_variant_entry,
    extract_artifact_paths,
)


@dataclass(frozen=True, slots=True)
class VideoBackendCapabilities:
    backend_id: str
    stage_types: tuple[str, ...]
    requires_input_image: bool = True
    supports_prompt_text: bool = False
    supports_negative_prompt: bool = False
    supports_multiple_anchors: bool = False
    artifact_type: str = "video"


@dataclass(slots=True)
class VideoExecutionRequest:
    backend_id: str
    stage_name: str
    stage_config: dict[str, Any]
    output_dir: Path
    input_image_path: Path | None = None
    image_name: str | None = None
    prompt: str = ""
    negative_prompt: str = ""
    job_id: str | None = None
    cancel_token: Any = None
    context_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class VideoExecutionResult:
    backend_id: str
    stage_name: str
    primary_path: str | None
    output_paths: list[str] = field(default_factory=list)
    manifest_path: str | None = None
    thumbnail_path: str | None = None
    frame_paths: list[str] = field(default_factory=list)
    artifact: dict[str, Any] = field(default_factory=dict)
    raw_result: dict[str, Any] = field(default_factory=dict)
    backend_metadata: dict[str, Any] = field(default_factory=dict)
    diagnostic_payload: dict[str, Any] = field(default_factory=dict)
    replay_manifest_fragment: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_stage_result(
        cls,
        *,
        backend_id: str,
        stage_name: str,
        result: dict[str, Any],
        backend_metadata: dict[str, Any] | None = None,
        diagnostic_payload: dict[str, Any] | None = None,
        replay_manifest_fragment: dict[str, Any] | None = None,
    ) -> "VideoExecutionResult":
        normalized = canonicalize_variant_entry(result, stage=stage_name)
        artifact = dict(normalized.get("artifact") or {})
        output_paths = extract_artifact_paths(normalized)
        primary_path = (
            artifact.get("primary_path")
            or normalized.get("output_path")
            or normalized.get("path")
            or normalized.get("video_path")
            or normalized.get("gif_path")
        )
        if not artifact or artifact.get("schema") != ARTIFACT_SCHEMA_VERSION:
            artifact = build_artifact_record(
                stage=stage_name,
                artifact_type="video",
                primary_path=primary_path,
                output_paths=output_paths,
                manifest_path=normalized.get("manifest_path"),
                thumbnail_path=normalized.get("thumbnail_path"),
                input_image_path=normalized.get("source_image_path")
                or normalized.get("input_image_path")
                or normalized.get("input_image"),
            )
        frame_paths = [str(item) for item in normalized.get("frame_paths") or [] if item]
        return cls(
            backend_id=backend_id,
            stage_name=stage_name,
            primary_path=str(primary_path) if primary_path else None,
            output_paths=[str(item) for item in output_paths if item],
            manifest_path=str(normalized.get("manifest_path")) if normalized.get("manifest_path") else None,
            thumbnail_path=str(normalized.get("thumbnail_path")) if normalized.get("thumbnail_path") else None,
            frame_paths=frame_paths,
            artifact=artifact,
            raw_result=normalized,
            backend_metadata=dict(backend_metadata or {}),
            diagnostic_payload=dict(diagnostic_payload or {}),
            replay_manifest_fragment=dict(replay_manifest_fragment or {}),
        )

    def to_variant_payload(self) -> dict[str, Any]:
        payload = dict(self.raw_result or {})
        if self.primary_path:
            payload.setdefault("path", self.primary_path)
            payload.setdefault("output_path", self.primary_path)
        if self.output_paths:
            payload["output_paths"] = list(self.output_paths)
        if self.manifest_path:
            payload["manifest_path"] = self.manifest_path
        if self.thumbnail_path:
            payload["thumbnail_path"] = self.thumbnail_path
        if self.frame_paths:
            payload["frame_paths"] = list(self.frame_paths)
        payload["artifact"] = dict(self.artifact or {})
        payload["video_backend_id"] = self.backend_id
        payload["video_backend_metadata"] = dict(self.backend_metadata or {})
        if self.diagnostic_payload:
            payload["video_backend_diagnostics"] = dict(self.diagnostic_payload)
        if self.replay_manifest_fragment:
            payload["video_replay_manifest"] = dict(self.replay_manifest_fragment)
        return canonicalize_variant_entry(payload, stage=self.stage_name)


class VideoBackendInterface(Protocol):
    backend_id: str
    capabilities: VideoBackendCapabilities

    def execute(self, pipeline: Any, request: VideoExecutionRequest) -> VideoExecutionResult | None:
        ...


__all__ = [
    "VideoBackendCapabilities",
    "VideoBackendInterface",
    "VideoExecutionRequest",
    "VideoExecutionResult",
]
