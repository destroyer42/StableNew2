"""Select a recorded History artifact by media type, not by its poster image.

Pure projection over a persisted result: no directory scanning, decoding or backend
access. A video bundle always takes precedence over a PNG thumbnail, even when
its recorded clip has gone missing. The GUI uses this projection for playback.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif"})
_VIDEO_SUFFIXES = frozenset({".mp4", ".mov", ".mkv", ".avi", ".webm", ".gif"})
_VIDEO_STAGES = frozenset({"svd_native", "video_workflow", "movie_assembly", "animatediff"})


@dataclass(frozen=True)
class RecordedArtifact:
    kind: Literal["video", "image", "frames", "none"]
    path: str | None = None
    message: str = ""


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _paths(payload: Mapping[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("primary_path", "video_path", "gif_path", "path", "output_path"):
        value = payload.get(key)
        if isinstance(value, (str, os.PathLike)) and str(value).strip():
            values.append(str(value))
    for key in ("video_paths", "gif_paths", "output_paths"):
        raw = payload.get(key)
        if isinstance(raw, (tuple, list)):
            values.extend(
                str(item)
                for item in raw
                if isinstance(item, (str, os.PathLike)) and str(item).strip()
            )
    return list(dict.fromkeys(values))


def _metadata(result: Mapping[str, Any]) -> Mapping[str, Any]:
    metadata = result.get("metadata")
    if isinstance(metadata, list):
        metadata = next((value for value in reversed(metadata) if isinstance(value, Mapping)), {})
    return _mapping(metadata)


def _video_bundles(result: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    bundles: list[Mapping[str, Any]] = []
    direct = _mapping(result.get("video_bundle"))
    if direct:
        bundles.append(direct)
    artifact = _mapping(result.get("artifact"))
    if str(artifact.get("artifact_type") or "").lower() == "video" or any(
        Path(path).suffix.lower() in _VIDEO_SUFFIXES for path in _paths(artifact)
    ):
        bundles.append(artifact)

    metadata = _metadata(result)
    for key in (
        "video_primary_artifact",
        "movie_assembly_artifact",
        "video_workflow_artifact",
        "svd_native_artifact",
        "animatediff_artifact",
    ):
        candidate = _mapping(metadata.get(key))
        if candidate:
            bundles.append(candidate)
    for key in ("video_artifacts", "video_backend_results"):
        aggregates = _mapping(metadata.get(key))
        bundles.extend(candidate for value in aggregates.values() if (candidate := _mapping(value)))
    for variant in result.get("variants") or []:
        if not isinstance(variant, Mapping):
            continue
        candidate = _mapping(variant.get("artifact"))
        if candidate and (
            str(candidate.get("artifact_type") or "").lower() == "video"
            or str(variant.get("stage") or "") in _VIDEO_STAGES
        ):
            bundles.append(candidate)
    return bundles


def _video_candidates(bundle: Mapping[str, Any]) -> list[str]:
    candidates = [path for path in _paths(bundle) if Path(path).suffix.lower() in _VIDEO_SUFFIXES]
    if candidates:
        return candidates
    for artifact in bundle.get("artifacts") or []:
        if isinstance(artifact, Mapping):
            candidates.extend(
                path for path in _paths(artifact) if Path(path).suffix.lower() in _VIDEO_SUFFIXES
            )
    return list(dict.fromkeys(candidates))


def _has_frames(bundle: Mapping[str, Any]) -> bool:
    frames = bundle.get("frame_paths")
    if isinstance(frames, (tuple, list)) and any(frames):
        return True
    if (
        str(bundle.get("artifact_type") or "").lower() == "video"
        or str(bundle.get("stage") or "") in _VIDEO_STAGES
    ):
        return any(Path(path).suffix.lower() in _IMAGE_SUFFIXES for path in _paths(bundle))
    return False


def resolve_recorded_artifact(
    result: Mapping[str, Any] | None,
    *,
    is_file: Callable[[str], bool] = os.path.isfile,
) -> RecordedArtifact:
    """Use persisted identity and the primary video path, never an image stand-in."""
    payload = _mapping(result)
    video_bundles = _video_bundles(payload)
    for bundle in video_bundles:
        candidates = _video_candidates(bundle)
        if candidates:
            primary = candidates[0]
            try:
                exists = bool(is_file(primary))
            except (OSError, ValueError):
                exists = False
            if exists:
                return RecordedArtifact("video", primary)
            return RecordedArtifact(
                "video", message=f"Recorded video file is missing: {Path(primary).name}"
            )
        if _has_frames(bundle):
            return RecordedArtifact(
                "frames", message="This job recorded frames, but no playable video clip."
            )
    if video_bundles:
        return RecordedArtifact(
            "video", message="This job recorded a video result without a playable video file."
        )

    artifacts = [_mapping(payload.get("artifact"))]
    for variant in payload.get("variants") or []:
        if isinstance(variant, Mapping):
            artifacts.append(_mapping(variant.get("artifact")))
    for artifact in artifacts:
        if not artifact:
            continue
        images = [path for path in _paths(artifact) if Path(path).suffix.lower() in _IMAGE_SUFFIXES]
        thumb = artifact.get("thumbnail_path")
        if not images and isinstance(thumb, str) and Path(thumb).suffix.lower() in _IMAGE_SUFFIXES:
            images = [thumb]
        if images:
            first = images[0]
            try:
                if is_file(first):
                    return RecordedArtifact("image", first)
            except (OSError, ValueError):
                pass
            return RecordedArtifact(
                "image", message=f"Recorded image file is missing: {Path(first).name}"
            )
    return RecordedArtifact("none", message="No recorded artifact for this job.")


__all__ = ["RecordedArtifact", "resolve_recorded_artifact"]
