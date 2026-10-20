"""Generic helpers for normalizing workflow-video output bundles.

PR-VIDEO-215: Provides one standard shape for video-artifact handoff between
pipeline results, history, and GUI surfaces.  All callers should consume this
bundle shape rather than digging through backend-local fields.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from src.video.video_backend_types import VideoExecutionResult


def build_video_artifact_bundle(
    *,
    stage: str,
    backend_id: str,
    primary_path: str | None,
    output_paths: list[str],
    video_paths: list[str] | None = None,
    gif_paths: list[str] | None = None,
    frame_paths: list[str] | None = None,
    manifest_path: str | None = None,
    manifest_paths: list[str] | None = None,
    thumbnail_path: str | None = None,
    source_image_path: str | None = None,
    artifact_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return a standardised video-artifact handoff bundle.

    Keys are stable and generic — no backend-local fields are included.
    """
    resolved_video_paths: list[str] = [str(p) for p in (video_paths or []) if p]
    resolved_gif_paths: list[str] = [str(p) for p in (gif_paths or []) if p]
    resolved_frame_paths: list[str] = [str(p) for p in (frame_paths or []) if p]
    resolved_output_paths: list[str] = [str(p) for p in output_paths if p]
    resolved_manifest_paths: list[str] = [str(p) for p in (manifest_paths or []) if p]

    if manifest_path:
        manifest_path_str = str(manifest_path)
        if manifest_path_str not in resolved_manifest_paths:
            resolved_manifest_paths = [manifest_path_str] + resolved_manifest_paths

    count = (
        len(resolved_output_paths)
        or len(resolved_video_paths)
        or len(resolved_gif_paths)
        or len(resolved_frame_paths)
    )

    return {
        "stage": str(stage or ""),
        "backend_id": str(backend_id or ""),
        "artifact_type": "video",
        "primary_path": str(primary_path) if primary_path else None,
        "output_paths": resolved_output_paths,
        "video_paths": resolved_video_paths,
        "gif_paths": resolved_gif_paths,
        "frame_paths": resolved_frame_paths,
        "manifest_path": resolved_manifest_paths[0] if resolved_manifest_paths else None,
        "manifest_paths": resolved_manifest_paths,
        "thumbnail_path": str(thumbnail_path) if thumbnail_path else None,
        "source_image_path": str(source_image_path) if source_image_path else None,
        "count": count,
        "artifacts": list(artifact_records or []),
    }


def bundle_from_execution_result(execution_result: VideoExecutionResult) -> dict[str, Any]:
    """Build a generic video-artifact bundle from a ``VideoExecutionResult`` instance."""
    variant_payload = (
        execution_result.to_variant_payload()
        if hasattr(execution_result, "to_variant_payload")
        else {}
    )
    artifact_records: list[dict[str, Any]] = []
    if getattr(execution_result, "artifact", None):
        artifact_records = [dict(execution_result.artifact)]

    return build_video_artifact_bundle(
        stage=str(getattr(execution_result, "stage_name", "") or ""),
        backend_id=str(getattr(execution_result, "backend_id", "") or ""),
        primary_path=getattr(execution_result, "primary_path", None),
        output_paths=[str(p) for p in (getattr(execution_result, "output_paths", None) or []) if p],
        video_paths=[str(p) for p in (variant_payload.get("video_paths") or []) if p],
        gif_paths=[str(p) for p in (variant_payload.get("gif_paths") or []) if p],
        frame_paths=[str(p) for p in (getattr(execution_result, "frame_paths", None) or []) if p],
        manifest_path=getattr(execution_result, "manifest_path", None),
        manifest_paths=(
            [str(execution_result.manifest_path)]
            if getattr(execution_result, "manifest_path", None)
            else []
        ),
        thumbnail_path=getattr(execution_result, "thumbnail_path", None),
        source_image_path=variant_payload.get("source_image_path"),
        artifact_records=artifact_records,
    )


def video_bundle_from_result(result: Any) -> dict[str, Any] | None:
    """The canonical video-artifact bundle a persisted job result carries, or ``None``.

    Read order mirrors how history stamps results: the top-level ``video_bundle``, then the runner's
    ``metadata.video_primary_artifact`` / ``video_artifacts`` / ``video_workflow_artifact``.  Pure; it
    inspects only the result mapping, never the file system.
    """

    if not isinstance(result, dict):
        return None
    bundle = result.get("video_bundle")
    if isinstance(bundle, dict) and bundle:
        return dict(bundle)
    metadata = result.get("metadata")
    if isinstance(metadata, list):
        metadata = next((item for item in reversed(metadata) if isinstance(item, dict)), None)
    if not isinstance(metadata, dict):
        return None
    for key in ("video_primary_artifact", "video_workflow_artifact"):
        candidate = metadata.get(key)
        if isinstance(candidate, dict) and candidate:
            return dict(candidate)
    artifacts = metadata.get("video_artifacts")
    if isinstance(artifacts, dict):
        for candidate in artifacts.values():
            if isinstance(candidate, dict) and candidate:
                return dict(candidate)
    return None


def extract_primary_video_path(bundle: dict[str, Any]) -> str | None:
    """Return the best primary output path from a video-artifact bundle."""
    primary = bundle.get("primary_path")
    if primary:
        return str(primary)
    for key in ("video_paths", "gif_paths", "output_paths", "frame_paths"):
        items = bundle.get(key)
        if isinstance(items, list) and items:
            return str(items[0])
    return None


def extract_video_frame_paths(bundle: dict[str, Any]) -> list[str]:
    """Return frame paths from a video-artifact bundle (useful for Movie Clips intake)."""
    frame_paths = bundle.get("frame_paths")
    if isinstance(frame_paths, list) and frame_paths:
        return [str(p) for p in frame_paths if p]
    return []


def extract_source_image_for_handoff(bundle: dict[str, Any]) -> str | None:
    """Return the best image path to use when handing a video result to Video Workflow.

    Preference order: thumbnail (a real frame) → source_image_path (original input).
    """
    thumbnail = bundle.get("thumbnail_path")
    if thumbnail:
        return str(thumbnail)
    source = bundle.get("source_image_path")
    if source:
        return str(source)
    # Last resort: first frame path
    frame_paths = bundle.get("frame_paths")
    if isinstance(frame_paths, list) and frame_paths:
        return str(frame_paths[0])
    return None


__all__ = [
    "build_video_artifact_bundle",
    "bundle_from_execution_result",
    "extract_primary_video_path",
    "extract_source_image_for_handoff",
    "extract_video_frame_paths",
    "video_bundle_from_result",
]
