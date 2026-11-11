"""Read-only history summaries for the native SVD tab."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from src.video.video_artifact_helpers import history_video_artifact_summary


def project_recent_svd_history(
    history_items: Iterable[Any],
    *,
    limit: int,
    read_manifest: Callable[[Iterable[str]], dict[str, Any]],
) -> list[dict[str, Any]]:
    """Project the SVD tab's history rows from an existing history snapshot."""
    records: list[dict[str, Any]] = []
    for entry in history_items:
        record = _build_svd_history_record(entry, read_manifest)
        if record is not None:
            records.append(record)
    records.sort(
        key=lambda item: _history_sort_key(
            item.get("completed_at") or item.get("started_at") or item.get("created_at")
        ),
        reverse=True,
    )
    return records[: max(int(limit), 1)]


def _history_sort_key(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _build_svd_history_record(
    entry: Any,
    read_manifest: Callable[[Iterable[str]], dict[str, Any]],
) -> dict[str, Any] | None:
    result = getattr(entry, "result", None)
    artifact = history_video_artifact_summary(result, preferred_stage="svd_native")

    variants = []
    if isinstance(result, dict):
        raw_variants = result.get("variants")
        if isinstance(raw_variants, list):
            variants = [item for item in raw_variants if isinstance(item, dict)]
    primary_variant = variants[0] if variants else {}
    artifacts = []
    if isinstance(artifact, dict):
        raw_artifacts = artifact.get("artifacts")
        if isinstance(raw_artifacts, list):
            artifacts = [item for item in raw_artifacts if isinstance(item, dict)]
    if not artifacts:
        artifacts = [
            dict(item["artifact"]) for item in variants if isinstance(item.get("artifact"), dict)
        ]
    primary_artifact = artifacts[0] if artifacts else {}

    manifest_candidates: list[str] = []
    if isinstance(artifact, dict):
        manifest_candidates.extend(str(item) for item in artifact.get("manifest_paths", []) if item)
    manifest_value = primary_variant.get("manifest_path") or primary_artifact.get("manifest_path")
    if manifest_value:
        manifest_candidates.append(str(manifest_value))
    manifest_payload = read_manifest(manifest_candidates)
    manifest_artifact = (
        dict(manifest_payload["artifact"])
        if isinstance(manifest_payload.get("artifact"), dict)
        else {}
    )

    if not isinstance(artifact, dict) and not manifest_payload and not primary_artifact:
        return None

    postprocess = primary_variant.get("postprocess")
    if not isinstance(postprocess, dict):
        manifest_postprocess = manifest_payload.get("postprocess")
        postprocess = manifest_postprocess if isinstance(manifest_postprocess, dict) else {}
    applied = [str(item) for item in postprocess.get("applied", []) if item]
    input_frame_count = postprocess.get("input_frame_count")
    output_frame_count = postprocess.get("output_frame_count")
    output_width = postprocess.get("output_width")
    output_height = postprocess.get("output_height")

    video_paths = [str(item) for item in (artifact or {}).get("video_paths", []) if item]
    if not video_paths:
        video_paths = [str(item) for item in manifest_payload.get("video_paths", []) if item]
    if not video_paths:
        video_value = primary_variant.get("video_path")
        if video_value:
            video_paths = [str(video_value)]

    gif_paths = [str(item) for item in (artifact or {}).get("gif_paths", []) if item]
    if not gif_paths:
        gif_paths = [str(item) for item in manifest_payload.get("gif_paths", []) if item]
    if not gif_paths:
        gif_value = primary_variant.get("gif_path")
        if gif_value:
            gif_paths = [str(gif_value)]

    output_paths = [str(item) for item in (artifact or {}).get("output_paths", []) if item]
    if not output_paths and isinstance(primary_artifact, dict):
        output_paths = [str(item) for item in primary_artifact.get("output_paths", []) if item]
    if not output_paths:
        output_paths = [str(item) for item in manifest_payload.get("output_paths", []) if item]
    if not output_paths:
        output_paths = [str(item) for item in manifest_payload.get("frame_paths", []) if item]
    if not output_paths and primary_variant.get("path"):
        output_paths = [str(primary_variant["path"])]

    manifest_paths = [str(item) for item in (artifact or {}).get("manifest_paths", []) if item]
    if not manifest_paths:
        manifest_paths = [str(item) for item in manifest_payload.get("manifest_paths", []) if item]
    if not manifest_paths and manifest_value:
        manifest_paths = [str(manifest_value)]

    thumbnail_path = (
        (artifact or {}).get("thumbnail_path")
        or primary_variant.get("thumbnail_path")
        or primary_artifact.get("thumbnail_path")
        or manifest_payload.get("thumbnail_path")
        or manifest_artifact.get("thumbnail_path")
    )
    source_image_path = (
        primary_variant.get("source_image_path")
        or primary_artifact.get("input_image_path")
        or manifest_payload.get("source_image_path")
        or manifest_artifact.get("input_image_path")
    )
    if not source_image_path:
        snapshot = getattr(entry, "snapshot", None)
        if isinstance(snapshot, dict):
            normalized = snapshot.get("normalized_job")
            if isinstance(normalized, dict):
                input_paths = normalized.get("input_image_paths")
                if isinstance(input_paths, list) and input_paths:
                    source_image_path = input_paths[0]
    primary_output = (
        (video_paths[0] if video_paths else None)
        or (gif_paths[0] if gif_paths else None)
        or (output_paths[0] if output_paths else None)
    )
    output_dir = None
    if primary_output:
        output_dir = str(Path(primary_output).parent)
    elif thumbnail_path:
        output_dir = str(Path(thumbnail_path).parent)
    elif manifest_paths:
        output_dir = str(Path(manifest_paths[0]).parent.parent)

    return {
        "job_id": getattr(entry, "job_id", ""),
        "status": getattr(
            getattr(entry, "status", None), "value", str(getattr(entry, "status", ""))
        ),
        "created_at": getattr(entry, "created_at", None),
        "started_at": getattr(entry, "started_at", None),
        "completed_at": getattr(entry, "completed_at", None),
        "source_image_path": str(source_image_path) if source_image_path else None,
        "thumbnail_path": str(thumbnail_path) if thumbnail_path else None,
        "video_path": video_paths[0] if video_paths else None,
        "gif_path": gif_paths[0] if gif_paths else None,
        "output_path": primary_output,
        "output_dir": output_dir,
        "manifest_path": manifest_paths[0] if manifest_paths else None,
        "frame_count": primary_variant.get("frame_count") or manifest_payload.get("frame_count"),
        "fps": primary_variant.get("fps") or manifest_payload.get("fps"),
        "model_id": primary_variant.get("model_id") or manifest_payload.get("model_id"),
        "count": (artifact or {}).get("count")
        or manifest_payload.get("count")
        or len(output_paths),
        "postprocess": postprocess or None,
        "postprocess_applied": applied,
        "postprocess_stage_count": len(applied),
        "postprocess_input_frame_count": input_frame_count,
        "postprocess_output_frame_count": output_frame_count,
        "postprocess_output_width": output_width,
        "postprocess_output_height": output_height,
    }
