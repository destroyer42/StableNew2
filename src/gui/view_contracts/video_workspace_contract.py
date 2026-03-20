from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.gui.view_contracts.movie_clips_contract import extract_source_paths_from_bundle
from src.video.video_artifact_helpers import extract_source_image_for_handoff


def _basename(path: str | None) -> str:
    if not path:
        return ""
    return Path(str(path)).name


def _listify(value: Any) -> list[str]:
    if isinstance(value, str):
        return [item.strip() for item in value.split(";") if item.strip()]
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


@dataclass(frozen=True)
class VideoWorkspaceSummary:
    headline: str
    detail: str
    empty_state: str = ""


def get_video_workspace_empty_state(surface: str) -> str:
    if surface == "video_workflow":
        return "Choose a source image and an end anchor to queue a workflow video job."
    if surface == "movie_clips":
        return "Choose a run folder, add images manually, or route a recent video result here."
    return "No source loaded."


def format_workflow_capability_label(spec: dict[str, Any] | None) -> str:
    if not isinstance(spec, dict) or not spec:
        return "No workflow selected."
    display_name = str(spec.get("display_name") or spec.get("workflow_id") or "Workflow").strip()
    backend = str(spec.get("backend_id") or "").strip()
    tags = [str(tag).strip() for tag in spec.get("capability_tags") or [] if str(tag).strip()]
    parts = [display_name]
    if backend:
        parts.append(f"backend={backend}")
    if tags:
        parts.append(", ".join(tags))
    return " | ".join(parts)


def summarize_video_workflow_source(
    *,
    source_image_path: str | None,
    workflow_spec: dict[str, Any] | None = None,
    end_anchor_path: str | None = None,
    mid_anchor_paths: list[str] | tuple[str, ...] | str | None = None,
    bundle: dict[str, Any] | None = None,
) -> VideoWorkspaceSummary:
    source_path = extract_source_image_for_handoff(bundle) if isinstance(bundle, dict) else None
    if not source_path:
        source_path = str(source_image_path or "").strip() or None
    if source_path:
        headline = f"Source: {_basename(source_path)}"
    else:
        headline = "Source: none selected"

    details: list[str] = []
    if workflow_spec:
        details.append(format_workflow_capability_label(workflow_spec))
    if end_anchor_path:
        details.append(f"End anchor: {_basename(str(end_anchor_path))}")
    mid_anchors = _listify(mid_anchor_paths)
    if mid_anchors:
        details.append(f"Mid anchors: {len(mid_anchors)}")
    if bundle and bundle.get("stage"):
        details.append(f"Handoff: {bundle.get('stage')}")

    return VideoWorkspaceSummary(
        headline=headline,
        detail=" | ".join(part for part in details if part),
        empty_state=get_video_workspace_empty_state("video_workflow"),
    )


def summarize_movie_clips_source(
    *,
    image_paths: list[str | Path] | None = None,
    bundle: dict[str, Any] | None = None,
) -> VideoWorkspaceSummary:
    if isinstance(bundle, dict):
        source_paths = extract_source_paths_from_bundle(bundle)
        if source_paths:
            stage = str(bundle.get("stage") or "").strip()
            label = f"{len(source_paths)} source item(s)"
            if stage == "assembled_video":
                label = "assembled video output"
            elif bundle.get("segment_provenance"):
                label = f"{len(source_paths)} segment clip(s)"
            return VideoWorkspaceSummary(
                headline=f"Source: {label}",
                detail=f"Loaded from {stage or 'video bundle'}",
                empty_state=get_video_workspace_empty_state("movie_clips"),
            )

    normalized_paths = [Path(item) for item in (image_paths or []) if str(item).strip()]
    if normalized_paths:
        if len(normalized_paths) == 1:
            headline = f"Source: {_basename(str(normalized_paths[0]))}"
        else:
            headline = f"Source: {len(normalized_paths)} image/frame item(s)"
        return VideoWorkspaceSummary(
            headline=headline,
            detail="Manual image sequence" if len(normalized_paths) > 1 else "Single selected source",
            empty_state=get_video_workspace_empty_state("movie_clips"),
        )

    return VideoWorkspaceSummary(
        headline="Source: none loaded",
        detail="",
        empty_state=get_video_workspace_empty_state("movie_clips"),
    )


__all__ = [
    "VideoWorkspaceSummary",
    "format_workflow_capability_label",
    "get_video_workspace_empty_state",
    "summarize_movie_clips_source",
    "summarize_video_workflow_source",
]
