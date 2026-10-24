from __future__ import annotations

from pathlib import Path
from tkinter import TclError
from typing import Any

from src.video.video_artifact_helpers import extract_source_image_for_handoff


def _select_tab(main_window: Any, tab: Any) -> None:
    notebook = getattr(main_window, "center_notebook", None)
    if notebook is not None:
        try:
            notebook.select(tab)
        except Exception:
            pass


def _apply_make_video_defaults(workflow_tab: Any) -> None:
    """Make Video preselects the recommended approved workflow (the tab keeps an approved choice)."""

    apply_defaults = getattr(workflow_tab, "apply_make_video_defaults", None)
    if callable(apply_defaults):
        apply_defaults()


def show_queue_view(main_window: Any) -> bool:
    """Bring the Pipeline tab (queue, running job and history) to the front; False when unavailable."""

    pipeline_tab = getattr(main_window, "pipeline_tab", None)
    notebook = getattr(main_window, "center_notebook", None)
    if pipeline_tab is None or notebook is None:
        return False
    try:
        notebook.select(pipeline_tab)
    except (TclError, AttributeError):
        return False
    return True


def route_image_to_video_workflow(
    *,
    main_window: Any,
    image_path: str | Path,
    status_message: str | None = None,
    lineage: dict[str, str] | None = None,
) -> str:
    workflow_tab = getattr(main_window, "video_workflow_tab", None)
    if workflow_tab is None:
        raise RuntimeError("Video Workflow tab is not available")
    setter = getattr(workflow_tab, "set_source_image_path", None)
    if not callable(setter):
        raise RuntimeError("Video Workflow tab does not support source handoff")
    _select_tab(main_window, workflow_tab)
    if lineage:
        setter(str(image_path), status_message=status_message, lineage=dict(lineage))
    else:
        setter(str(image_path), status_message=status_message)
    _apply_make_video_defaults(workflow_tab)
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
            main_window=main_window,
            image_path=paths[0],
            status_message=status_message,
            lineage=dict((lineage_by_path or {}).get(paths[0]) or {}),
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
    _apply_make_video_defaults(workflow_tab)
    return paths


def route_images_to_review(
    *,
    main_window: Any,
    image_paths: list[str | Path],
    status_message: str | None = None,
) -> list[str]:
    """Hand an ORDERED list of existing images to Review's selection (intent only; nothing is queued).

    Replacing unsent Review work asks Replace/Cancel first. When the operator cancels, nothing changes (Review keeps
    its state, navigation stays where it was) and the result is an empty list.
    """

    paths = [str(path) for path in image_paths if str(path).strip()]
    if not paths:
        raise ValueError("No images were provided for the Review handoff")
    review_tab = getattr(main_window, "review_tab", None)
    if review_tab is None:
        raise RuntimeError("Review tab is not available")
    loader = getattr(review_tab, "load_selected_images", None)
    if not callable(loader):
        raise RuntimeError("Review tab does not support image handoff")
    if not loader(paths, status_message=status_message):
        return []
    _select_tab(main_window, review_tab)
    return paths


def route_images_to_photo_optimize(
    *,
    main_window: Any,
    image_paths: list[str | Path],
    status_message: str | None = None,
) -> list[str]:
    """Offer ORDERED existing images to the Managed Photo Set (import is planned and operator-confirmed there).

    This carries file paths only: no Review state, History lineage or prompt text travels with it. Nothing is
    copied or queued until the operator confirms the import inside Photo Optimize.
    """

    paths = [str(path) for path in image_paths if str(path).strip()]
    if not paths:
        raise ValueError("No images were provided for the Managed Photo Set")
    photo_tab = getattr(main_window, "photo_optimize_tab", None)
    if photo_tab is None:
        raise RuntimeError("Photo Optimize tab is not available")
    receiver = getattr(photo_tab, "receive_review_handoff", None)
    if not callable(receiver):
        raise RuntimeError("Photo Optimize tab does not support image handoff")
    _select_tab(main_window, photo_tab)
    receiver(paths, status_message=status_message)
    return paths


def route_history_handoff_to_review(*, main_window: Any, handoff: Any) -> None:
    """Hand one recorded History image (with its job/artifact identity) to Review (intent only; nothing is queued)."""

    review_tab = getattr(main_window, "review_tab", None)
    if review_tab is None:
        raise RuntimeError("Review tab is not available")
    loader = getattr(review_tab, "load_history_iterate_handoff", None)
    if not callable(loader):
        raise RuntimeError("Review tab does not support History handoff")
    _select_tab(main_window, review_tab)
    loader(handoff)


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
    _apply_make_video_defaults(workflow_tab)
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
    "route_history_handoff_to_review",
    "route_image_to_video_workflow",
    "route_images_to_photo_optimize",
    "route_images_to_review",
    "route_images_to_video_workflow",
    "show_queue_view",
]
