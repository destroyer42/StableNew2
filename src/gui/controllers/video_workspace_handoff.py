from __future__ import annotations

from pathlib import Path
from typing import Any

from src.video.video_artifact_helpers import extract_source_image_for_handoff


def _select_tab(main_window: Any, tab: Any) -> None:
    notebook = getattr(main_window, "center_notebook", None)
    if notebook is not None:
        try:
            notebook.select(tab)
        except Exception:
            pass


def route_image_to_video_workflow(
    *,
    main_window: Any,
    image_path: str | Path,
    status_message: str | None = None,
) -> str:
    workflow_tab = getattr(main_window, "video_workflow_tab", None)
    if workflow_tab is None:
        raise RuntimeError("Video Workflow tab is not available")
    setter = getattr(workflow_tab, "set_source_image_path", None)
    if not callable(setter):
        raise RuntimeError("Video Workflow tab does not support source handoff")
    _select_tab(main_window, workflow_tab)
    setter(str(image_path), status_message=status_message)
    return str(image_path)


def route_images_to_video_workflow(
    *,
    main_window: Any,
    image_paths: list[str | Path],
    lineage_by_path: dict[str, dict[str, str]] | None = None,
    status_message: str | None = None,
) -> list[str]:
    """Hand an ORDERED list of images to the Video Workflow tab as batch sources.

    Transfers intent only: nothing is assessed, prepared or queued.  One image keeps the
    established single-source handoff exactly, so existing behavior is unchanged."""

    paths = [str(path) for path in image_paths if str(path).strip()]
    if not paths:
        raise ValueError("No images were provided for the Video Workflow handoff")
    if len(paths) == 1:
        route_image_to_video_workflow(
            main_window=main_window, image_path=paths[0], status_message=status_message
        )
        return paths
    workflow_tab = getattr(main_window, "video_workflow_tab", None)
    if workflow_tab is None:
        raise RuntimeError("Video Workflow tab is not available")
    setter = getattr(workflow_tab, "set_source_batch", None)
    if not callable(setter):
        raise RuntimeError("Video Workflow tab does not support multi-source handoff")
    _select_tab(main_window, workflow_tab)
    setter(paths, lineage_by_path=dict(lineage_by_path or {}), status_message=status_message)
    return paths


def route_bundle_to_video_workflow(
    *,
    main_window: Any,
    bundle: dict[str, Any],
    status_message: str | None = None,
) -> str | None:
    workflow_tab = getattr(main_window, "video_workflow_tab", None)
    if workflow_tab is None:
        raise RuntimeError("Video Workflow tab is not available")
    setter = getattr(workflow_tab, "set_source_bundle", None)
    if not callable(setter):
        raise RuntimeError("Video Workflow tab does not support bundle handoff")
    _select_tab(main_window, workflow_tab)
    setter(dict(bundle), status_message=status_message)
    return extract_source_image_for_handoff(bundle)


def route_image_to_movie_clips(
    *,
    main_window: Any,
    image_path: str | Path,
    status_message: str | None = None,
) -> list[str]:
    movie_clips_tab = getattr(main_window, "movie_clips_tab", None)
    if movie_clips_tab is None:
        raise RuntimeError("Movie Clips tab is not available")
    setter = getattr(movie_clips_tab, "set_source_frame_paths", None)
    if not callable(setter):
        raise RuntimeError("Movie Clips tab does not support image handoff")
    _select_tab(main_window, movie_clips_tab)
    setter([str(image_path)], status_message=status_message)
    return [str(image_path)]


def route_bundle_to_movie_clips(
    *,
    main_window: Any,
    bundle: dict[str, Any],
    status_message: str | None = None,
) -> None:
    movie_clips_tab = getattr(main_window, "movie_clips_tab", None)
    if movie_clips_tab is None:
        raise RuntimeError("Movie Clips tab is not available")
    setter = getattr(movie_clips_tab, "set_source_bundle", None)
    if not callable(setter):
        raise RuntimeError("Movie Clips tab does not support bundle handoff")
    _select_tab(main_window, movie_clips_tab)
    setter(dict(bundle), status_message=status_message)


__all__ = [
    "route_bundle_to_movie_clips",
    "route_bundle_to_video_workflow",
    "route_image_to_movie_clips",
    "route_image_to_video_workflow",
    "route_images_to_video_workflow",
]
