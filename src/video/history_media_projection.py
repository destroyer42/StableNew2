"""Read-only media-selection decisions over existing Job History entries.

History handoffs (SVD, Video Workflow, Movie Clips) and the tabs' "latest output" pickers choose an
image or a video bundle from entries the application already holds.  These helpers take those entries
as data and own no state, so the controller keeps only navigation, logging and error reporting.

Deliberately distinct from ``recent_video_outputs`` (completed, playable videos only) and from
``video_bundle_from_result`` (different empty-bundle and metadata-fallback rules).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from src.video.video_artifact_helpers import history_video_artifact_summary

_IMAGE_OUTPUT_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif"}


def history_image_candidates(entry: Any) -> list[str]:
    """Return an entry's possible image paths in preference order, without duplicates."""
    candidates: list[str] = []
    result = getattr(entry, "result", None)
    if isinstance(result, dict):
        artifact = result.get("artifact")
        if isinstance(artifact, Mapping):
            artifact_paths = artifact.get("output_paths") or [artifact.get("primary_path")]
            candidates.extend(str(item) for item in artifact_paths if item)
        for key in ("output_paths", "frame_paths", "video_paths", "gif_paths"):
            value = result.get(key)
            if isinstance(value, list):
                candidates.extend(str(item) for item in value if item)
        path_value = result.get("path")
        if path_value:
            candidates.append(str(path_value))
        thumbnail = result.get("thumbnail_path")
        if thumbnail:
            candidates.append(str(thumbnail))
    snapshot = getattr(entry, "snapshot", None)
    if isinstance(snapshot, dict):
        normalized = snapshot.get("normalized_job")
        if isinstance(normalized, dict):
            value = normalized.get("output_paths")
            if isinstance(value, list):
                candidates.extend(str(item) for item in value if item)
            thumbnail = normalized.get("thumbnail_path")
            if thumbnail:
                candidates.append(str(thumbnail))

    # Preserve the first usable candidate as the handoff preference.
    return list(dict.fromkeys(candidate for candidate in candidates if candidate))


def history_image_path(entry: Any) -> str | None:
    """Return the first existing image file among an entry's candidates, or ``None``."""
    for candidate in history_image_candidates(entry):
        path = Path(candidate)
        if path.suffix.lower() in _IMAGE_OUTPUT_EXTENSIONS and path.exists():
            return str(path)
    return None


def history_video_bundle(entry: Any) -> dict[str, Any] | None:
    """Return the video bundle an entry's result records, or ``None``.

    A recorded top-level ``video_bundle`` dict wins (even an empty one); otherwise the bundle is
    projected from the result's video artifact summary.
    """
    result = getattr(entry, "result", None)
    if not isinstance(result, dict):
        return None
    bundle = result.get("video_bundle")
    if isinstance(bundle, dict):
        return dict(bundle)
    artifact = history_video_artifact_summary(result)
    if not isinstance(artifact, dict):
        return None
    return {
        "primary_path": artifact.get("primary_path"),
        "stage": artifact.get("stage"),
        "backend_id": artifact.get("backend_id"),
        "artifact_type": "video",
        "thumbnail_path": artifact.get("thumbnail_path"),
        "manifest_paths": list(artifact.get("manifest_paths") or []),
        "output_paths": list(artifact.get("output_paths") or []),
        "video_paths": list(artifact.get("video_paths") or []),
        "gif_paths": list(artifact.get("gif_paths") or []),
        "frame_paths": list(artifact.get("frame_paths") or []),
        "source_image_path": artifact.get("source_image_path"),
        "count": artifact.get("count"),
    }


def latest_history_image_path(entries: Iterable[Any]) -> str | None:
    """Return the first image path found scanning ``entries`` in the order given."""
    for entry in entries:
        image_path = history_image_path(entry)
        if image_path is not None:
            return image_path
    return None


def latest_history_video_bundle(entries: Iterable[Any]) -> dict[str, Any] | None:
    """Return the first bundle with a primary, output or frame path, in the order given.

    Neither status nor file existence is consulted, and ``video_paths`` alone does not qualify.
    """
    for entry in entries:
        bundle = history_video_bundle(entry)
        if isinstance(bundle, dict) and (
            bundle.get("primary_path") or bundle.get("output_paths") or bundle.get("frame_paths")
        ):
            return bundle
    return None
