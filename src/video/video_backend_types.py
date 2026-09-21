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

VIDEO_TASK_IMAGE_TO_VIDEO = "image_to_video"
# Only tasks StableNew can actually execute are enumerated; a future task is added here together
# with a backend that declares it, never merely to reserve a name.
KNOWN_VIDEO_TASKS = frozenset({VIDEO_TASK_IMAGE_TO_VIDEO})

CONTROL_SOURCE_IMAGE = "source_image"
CONTROL_PROMPT_TEXT = "prompt_text"
CONTROL_NEGATIVE_PROMPT = "negative_prompt"
CONTROL_START_ANCHOR = "start_anchor"
CONTROL_END_ANCHOR = "end_anchor"
CONTROL_MID_ANCHORS = "mid_anchors"
CONTROL_CONTROL_VIDEO = "control_video"
CONTROL_POSE_VIDEO = "pose_video"
CONTROL_CAMERA_INTENT = "camera_intent"
# Controls are semantic input forms, never model or workflow names.
KNOWN_VIDEO_CONTROLS = frozenset(
    {
        CONTROL_SOURCE_IMAGE,
        CONTROL_PROMPT_TEXT,
        CONTROL_NEGATIVE_PROMPT,
        CONTROL_START_ANCHOR,
        CONTROL_END_ANCHOR,
        CONTROL_MID_ANCHORS,
        CONTROL_CONTROL_VIDEO,
        CONTROL_POSE_VIDEO,
        CONTROL_CAMERA_INTENT,
    }
)
_ANCHOR_CONTROLS = (CONTROL_START_ANCHOR, CONTROL_END_ANCHOR, CONTROL_MID_ANCHORS)


@dataclass(frozen=True, slots=True)
class VideoBackendCapabilities:
    """What a backend declares it can execute.

    ``tasks`` and ``controls`` are the canonical contract; ``required_controls`` are the controls
    a request must carry.  Identity preservation is deliberately *not* a capability: it is an
    observed, qualified result, not a deterministic execution feature.

    ``stage_types`` and the ``requires_input_image`` / ``supports_*`` flags are bounded legacy
    input sugar: they are folded into ``controls`` / ``required_controls`` on construction and
    re-synced, so there is one source of truth.  Remove them once no historical stage-owned
    routing and no legacy-flag construction remains (see PR-VID-120 record).
    """

    backend_id: str
    stage_types: tuple[str, ...] = ()
    requires_input_image: bool = True
    supports_prompt_text: bool = False
    supports_negative_prompt: bool = False
    supports_multiple_anchors: bool = False
    artifact_type: str = "video"
    tasks: tuple[str, ...] = (VIDEO_TASK_IMAGE_TO_VIDEO,)
    controls: tuple[str, ...] = ()
    required_controls: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        controls = set(self.controls)
        required = set(self.required_controls)
        if not controls:  # legacy flag construction
            controls.add(CONTROL_SOURCE_IMAGE)
            if self.requires_input_image:
                required.add(CONTROL_SOURCE_IMAGE)
            if self.supports_prompt_text:
                controls.add(CONTROL_PROMPT_TEXT)
            if self.supports_negative_prompt:
                controls.add(CONTROL_NEGATIVE_PROMPT)
            if self.supports_multiple_anchors:
                controls.update(_ANCHOR_CONTROLS)
        unknown = sorted((controls | required) - KNOWN_VIDEO_CONTROLS)
        if unknown:
            raise ValueError(
                f"Video backend '{self.backend_id}' declares unknown controls {unknown}"
            )
        if not required <= controls:
            raise ValueError(f"Video backend '{self.backend_id}' requires undeclared controls")
        tasks = tuple(dict.fromkeys(str(t).strip() for t in self.tasks if str(t).strip()))
        unknown_tasks = sorted(set(tasks) - KNOWN_VIDEO_TASKS)
        if not tasks or unknown_tasks:
            raise ValueError(
                f"Video backend '{self.backend_id}' declares unsupported tasks {unknown_tasks or tasks}"
            )
        object.__setattr__(self, "tasks", tasks)
        object.__setattr__(self, "controls", tuple(sorted(controls)))
        object.__setattr__(self, "required_controls", tuple(sorted(required)))
        object.__setattr__(self, "requires_input_image", CONTROL_SOURCE_IMAGE in required)
        object.__setattr__(self, "supports_prompt_text", CONTROL_PROMPT_TEXT in controls)
        object.__setattr__(self, "supports_negative_prompt", CONTROL_NEGATIVE_PROMPT in controls)
        object.__setattr__(
            self, "supports_multiple_anchors", bool(controls & set(_ANCHOR_CONTROLS))
        )


@dataclass(slots=True)
class VideoExecutionRequest:
    """Neutral request handed to a video backend.

    ``task`` and ``requested_controls`` are set by the video resolver from explicit intent (or,
    for historical stage-owned records, the bounded compatibility mapping) and validated against
    the selected backend before dispatch; nothing is dropped or substituted.  Raw workflow or
    model payloads never belong here: they stay adapter-private (``backend_options`` carries only
    opaque adapter options).
    """

    backend_id: str
    stage_name: str
    stage_config: dict[str, Any]
    output_dir: Path
    input_image_path: Path | None = None
    start_anchor_path: Path | None = None
    end_anchor_path: Path | None = None
    mid_anchor_paths: list[Path] = field(default_factory=list)
    image_name: str | None = None
    prompt: str = ""
    negative_prompt: str = ""
    motion_profile: str = ""
    job_id: str | None = None
    workflow_id: str | None = None
    workflow_version: str | None = None
    workflow_inputs: dict[str, Any] = field(default_factory=dict)
    backend_options: dict[str, Any] = field(default_factory=dict)
    cancel_token: Any = None
    context_metadata: dict[str, Any] = field(default_factory=dict)
    task: str = VIDEO_TASK_IMAGE_TO_VIDEO
    requested_controls: tuple[str, ...] = ()


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
    ) -> VideoExecutionResult:
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
            manifest_path=str(normalized.get("manifest_path"))
            if normalized.get("manifest_path")
            else None,
            thumbnail_path=str(normalized.get("thumbnail_path"))
            if normalized.get("thumbnail_path")
            else None,
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

    def execute(
        self, pipeline: Any, request: VideoExecutionRequest
    ) -> VideoExecutionResult | None: ...


__all__ = [
    "CONTROL_CAMERA_INTENT",
    "CONTROL_CONTROL_VIDEO",
    "CONTROL_END_ANCHOR",
    "CONTROL_MID_ANCHORS",
    "CONTROL_NEGATIVE_PROMPT",
    "CONTROL_POSE_VIDEO",
    "CONTROL_PROMPT_TEXT",
    "CONTROL_SOURCE_IMAGE",
    "CONTROL_START_ANCHOR",
    "KNOWN_VIDEO_CONTROLS",
    "KNOWN_VIDEO_TASKS",
    "VIDEO_TASK_IMAGE_TO_VIDEO",
    "VideoBackendCapabilities",
    "VideoBackendInterface",
    "VideoExecutionRequest",
    "VideoExecutionResult",
]
