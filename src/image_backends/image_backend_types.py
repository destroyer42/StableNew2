"""Typed, StableNew-owned contracts for still-image execution backends."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from src.pipeline.artifact_contract import (
    ARTIFACT_SCHEMA_VERSION,
    build_artifact_record,
    canonicalize_variant_entry,
    extract_artifact_paths,
)

DEFAULT_IMAGE_BACKEND_ID = "a1111_webui"


def normalize_image_backend_options(
    existing_options: Any,
    *,
    backend_id: str = DEFAULT_IMAGE_BACKEND_ID,
) -> dict[str, Any]:
    """Persist explicit backend identity for newly constructed image work.

    This is intentionally a construction-time operation.  The execution
    resolver remains the sole compatibility authority for historical records
    which were persisted before image backend identity existed.
    """

    if existing_options is None:
        options: dict[str, Any] = {}
    elif isinstance(existing_options, Mapping):
        options = dict(existing_options)
    else:
        raise ValueError("backend_options must be a mapping for image work")

    image_options = options.get("image")
    if image_options is None:
        image = {}
    elif isinstance(image_options, Mapping):
        image = dict(image_options)
    else:
        raise ValueError("backend_options.image must be a mapping")

    explicit_backend_id = image.get("backend_id", backend_id)
    if not isinstance(explicit_backend_id, str):
        raise ValueError("backend_options.image.backend_id must be a string")
    normalized_backend_id = explicit_backend_id.strip() or backend_id
    if not normalized_backend_id:
        raise ValueError("backend_options.image.backend_id must not be blank")
    image["backend_id"] = normalized_backend_id
    options["image"] = image
    return options


def resolve_image_backend_id(backend_options: Any) -> str:
    """Resolve the sole bounded historical compatibility default."""

    options = dict(backend_options or {}) if isinstance(backend_options, Mapping) else {}
    image_options = options.get("image")
    if not isinstance(image_options, Mapping):
        return DEFAULT_IMAGE_BACKEND_ID
    backend_id = str(image_options.get("backend_id") or "").strip()
    return backend_id or DEFAULT_IMAGE_BACKEND_ID


@dataclass(frozen=True, slots=True)
class ImageBackendCapabilities:
    backend_id: str
    stage_types: tuple[str, ...]
    requires_input_image: bool = False
    supports_prompt_text: bool = True
    supports_negative_prompt: bool = True
    artifact_type: str = "image"


@dataclass(slots=True)
class ImageExecutionRequest:
    backend_id: str
    stage_name: str
    stage_config: dict[str, Any]
    output_dir: Path
    input_image_path: Path | None = None
    image_name: str | None = None
    prompt: str = ""
    negative_prompt: str = ""
    selected_model: str | None = None
    selected_vae: str | None = None
    sampler: str | None = None
    scheduler: str | None = None
    steps: int | None = None
    cfg_scale: float | None = None
    width: int | None = None
    height: int | None = None
    seed: int | None = None
    image_count: int = 1
    execution_config: dict[str, Any] = field(default_factory=dict)
    job_id: str | None = None
    backend_options: dict[str, Any] = field(default_factory=dict)
    cancel_token: Any = None
    context_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ImageExecutionResult:
    backend_id: str
    stage_name: str
    primary_path: str | None
    output_paths: list[str] = field(default_factory=list)
    manifest_path: str | None = None
    thumbnail_path: str | None = None
    artifact: dict[str, Any] = field(default_factory=dict)
    raw_result: dict[str, Any] = field(default_factory=dict)
    backend_metadata: dict[str, Any] = field(default_factory=dict)
    diagnostic_payload: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_stage_result(
        cls,
        *,
        backend_id: str,
        stage_name: str,
        result: dict[str, Any],
        backend_metadata: dict[str, Any] | None = None,
    ) -> ImageExecutionResult:
        normalized = canonicalize_variant_entry(result, stage=stage_name)
        artifact = dict(normalized.get("artifact") or {})
        output_paths = [str(item) for item in extract_artifact_paths(normalized) if item]
        primary_path = artifact.get("primary_path") or normalized.get("path") or normalized.get("output_path")
        if not artifact or artifact.get("schema") != ARTIFACT_SCHEMA_VERSION:
            artifact = build_artifact_record(
                stage=stage_name,
                artifact_type="image",
                primary_path=primary_path,
                output_paths=output_paths,
                manifest_path=normalized.get("manifest_path"),
                thumbnail_path=normalized.get("thumbnail_path"),
                input_image_path=normalized.get("input_image_path"),
            )
        return cls(
            backend_id=backend_id,
            stage_name=stage_name,
            primary_path=str(primary_path) if primary_path else None,
            output_paths=output_paths,
            manifest_path=str(normalized["manifest_path"]) if normalized.get("manifest_path") else None,
            thumbnail_path=str(normalized["thumbnail_path"]) if normalized.get("thumbnail_path") else None,
            artifact=artifact,
            raw_result=normalized,
            backend_metadata=dict(backend_metadata or {}),
        )

    def to_variant_payload(self) -> dict[str, Any]:
        payload = dict(self.raw_result)
        if self.primary_path:
            payload.setdefault("path", self.primary_path)
            payload.setdefault("output_path", self.primary_path)
        if self.output_paths:
            payload["output_paths"] = list(self.output_paths)
        payload["artifact"] = dict(self.artifact)
        payload["image_backend_id"] = self.backend_id
        payload["image_backend_metadata"] = dict(self.backend_metadata)
        return canonicalize_variant_entry(payload, stage=self.stage_name)


class ImageBackendInterface(Protocol):
    backend_id: str
    capabilities: ImageBackendCapabilities

    def execute(self, pipeline: Any, request: ImageExecutionRequest) -> ImageExecutionResult | None: ...
