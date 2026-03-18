from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ARTIFACT_SCHEMA_VERSION = "stablenew.artifact.v2.6"

_VIDEO_STAGES = {"animatediff", "svd_native"}


def _coerce_path(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _dedupe_paths(values: Sequence[Any] | None) -> list[str]:
    seen: set[str] = set()
    paths: list[str] = []
    for value in values or []:
        text = _coerce_path(value)
        if not text or text in seen:
            continue
        seen.add(text)
        paths.append(text)
    return paths


def infer_artifact_type(stage: str | None, payload: Mapping[str, Any] | None = None) -> str:
    stage_name = str(stage or "").strip().lower()
    data = dict(payload or {})
    if stage_name in _VIDEO_STAGES:
        return "video"
    if _coerce_path(data.get("video_path")) or _coerce_path(data.get("gif_path")):
        return "video"
    frame_paths = data.get("frame_paths")
    if isinstance(frame_paths, Sequence) and not isinstance(frame_paths, (str, bytes)):
        if any(_coerce_path(path) for path in frame_paths):
            return "video"
    return "image"


def build_artifact_record(
    *,
    stage: str,
    artifact_type: str,
    primary_path: str | None,
    output_paths: Sequence[Any] | None = None,
    manifest_path: str | None = None,
    thumbnail_path: str | None = None,
    input_image_path: str | None = None,
) -> dict[str, Any]:
    outputs = _dedupe_paths(output_paths)
    primary = _coerce_path(primary_path)
    if primary and primary not in outputs:
        outputs.insert(0, primary)
    return {
        "schema": ARTIFACT_SCHEMA_VERSION,
        "stage": str(stage or "").strip() or "unknown",
        "artifact_type": artifact_type,
        "primary_path": primary,
        "output_paths": outputs,
        "manifest_path": _coerce_path(manifest_path),
        "thumbnail_path": _coerce_path(thumbnail_path),
        "input_image_path": _coerce_path(input_image_path),
    }


def canonicalize_variant_entry(
    entry: Mapping[str, Any] | None,
    *,
    stage: str | None = None,
) -> dict[str, Any]:
    data = dict(entry or {})
    stage_name = str(data.get("stage") or stage or "").strip() or "unknown"
    manifest_path = _coerce_path(data.get("manifest_path") or data.get("metadata_path"))
    primary_path = _coerce_path(
        data.get("path")
        or data.get("output_path")
        or data.get("video_path")
        or data.get("gif_path")
    )

    output_paths = _dedupe_paths(data.get("output_paths"))
    if not output_paths:
        all_paths = data.get("all_paths")
        if isinstance(all_paths, Sequence) and not isinstance(all_paths, (str, bytes)):
            output_paths = _dedupe_paths(all_paths)
    if not output_paths:
        frame_paths = data.get("frame_paths")
        if isinstance(frame_paths, Sequence) and not isinstance(frame_paths, (str, bytes)):
            output_paths = _dedupe_paths(frame_paths)
    if not output_paths and primary_path:
        output_paths = [primary_path]

    artifact = dict(data.get("artifact") or {})
    if not artifact or artifact.get("schema") != ARTIFACT_SCHEMA_VERSION:
        artifact = build_artifact_record(
            stage=stage_name,
            artifact_type=infer_artifact_type(stage_name, data),
            primary_path=primary_path,
            output_paths=output_paths,
            manifest_path=manifest_path,
            thumbnail_path=_coerce_path(data.get("thumbnail_path")),
            input_image_path=_coerce_path(
                data.get("input_image")
                or data.get("input_image_path")
                or data.get("source_image_path")
            ),
        )

    if artifact.get("primary_path") and not primary_path:
        primary_path = artifact["primary_path"]
    output_paths = _dedupe_paths(artifact.get("output_paths") or output_paths)

    data["stage"] = stage_name
    if primary_path:
        data.setdefault("path", primary_path)
        data.setdefault("output_path", primary_path)
    if output_paths:
        data.setdefault("all_paths", output_paths)
        data["output_paths"] = output_paths
    if manifest_path:
        data["manifest_path"] = manifest_path
    data["artifact"] = artifact
    return data


def canonicalize_variant_entries(entries: Sequence[Mapping[str, Any] | None] | None) -> list[dict[str, Any]]:
    return [canonicalize_variant_entry(entry) for entry in entries or [] if entry is not None]


def extract_artifact_paths(entry: Mapping[str, Any] | None) -> list[str]:
    data = dict(entry or {})
    artifact = data.get("artifact") or {}
    if isinstance(artifact, Mapping):
        paths = _dedupe_paths(artifact.get("output_paths"))
        if paths:
            return paths
        primary = _coerce_path(artifact.get("primary_path"))
        if primary:
            return [primary]

    for key in ("output_paths", "all_paths", "frame_paths"):
        raw = data.get(key)
        if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
            paths = _dedupe_paths(raw)
            if paths:
                return paths

    for key in ("path", "output_path", "video_path", "gif_path"):
        path = _coerce_path(data.get(key))
        if path:
            return [path]
    return []


def artifact_manifest_payload(
    *,
    stage: str,
    image_or_output_path: Path | str,
    manifest_path: Path | str | None,
    output_paths: Sequence[Any] | None = None,
    thumbnail_path: Path | str | None = None,
    input_image_path: Path | str | None = None,
    artifact_type: str | None = None,
) -> dict[str, Any]:
    primary_path = _coerce_path(image_or_output_path)
    stage_name = str(stage or "").strip() or "unknown"
    return build_artifact_record(
        stage=stage_name,
        artifact_type=artifact_type or infer_artifact_type(stage_name, {"path": primary_path}),
        primary_path=primary_path,
        output_paths=output_paths or ([primary_path] if primary_path else []),
        manifest_path=_coerce_path(manifest_path),
        thumbnail_path=_coerce_path(thumbnail_path),
        input_image_path=_coerce_path(input_image_path),
    )


__all__ = [
    "ARTIFACT_SCHEMA_VERSION",
    "artifact_manifest_payload",
    "build_artifact_record",
    "canonicalize_variant_entries",
    "canonicalize_variant_entry",
    "extract_artifact_paths",
    "infer_artifact_type",
]
