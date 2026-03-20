from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.gui.controllers.video_workspace_handoff import (
    route_bundle_to_movie_clips,
    route_bundle_to_video_workflow,
    route_image_to_movie_clips,
    route_image_to_video_workflow,
)


class _NotebookStub:
    def __init__(self) -> None:
        self.selected = None

    def select(self, tab) -> None:
        self.selected = tab


@pytest.mark.gui
def test_route_bundle_to_video_workflow_selects_tab_and_uses_bundle() -> None:
    workflow_tab = SimpleNamespace(set_source_bundle=lambda bundle, status_message=None: None)
    notebook = _NotebookStub()
    main_window = SimpleNamespace(video_workflow_tab=workflow_tab, center_notebook=notebook)

    routed = route_bundle_to_video_workflow(
        main_window=main_window,
        bundle={"thumbnail_path": "C:/tmp/frame_001.png"},
        status_message="loaded",
    )

    assert routed == "C:/tmp/frame_001.png"
    assert notebook.selected is workflow_tab


@pytest.mark.gui
def test_route_image_to_video_workflow_selects_tab() -> None:
    calls: list[tuple[str, str | None]] = []
    workflow_tab = SimpleNamespace(
        set_source_image_path=lambda path, status_message=None: calls.append((path, status_message))
    )
    notebook = _NotebookStub()
    main_window = SimpleNamespace(video_workflow_tab=workflow_tab, center_notebook=notebook)

    routed = route_image_to_video_workflow(
        main_window=main_window,
        image_path="C:/tmp/source.png",
        status_message="loaded",
    )

    assert routed == "C:/tmp/source.png"
    assert notebook.selected is workflow_tab
    assert calls == [("C:/tmp/source.png", "loaded")]


@pytest.mark.gui
def test_route_bundle_to_movie_clips_selects_tab() -> None:
    calls: list[tuple[dict[str, str], str | None]] = []
    movie_tab = SimpleNamespace(
        set_source_bundle=lambda bundle, status_message=None: calls.append((bundle, status_message))
    )
    notebook = _NotebookStub()
    main_window = SimpleNamespace(movie_clips_tab=movie_tab, center_notebook=notebook)

    route_bundle_to_movie_clips(
        main_window=main_window,
        bundle={"primary_path": "C:/tmp/clip.mp4", "output_paths": ["C:/tmp/clip.mp4"]},
        status_message="movie",
    )

    assert notebook.selected is movie_tab
    assert calls[0][1] == "movie"


@pytest.mark.gui
def test_route_image_to_movie_clips_selects_tab() -> None:
    calls: list[tuple[list[str], str | None]] = []
    movie_tab = SimpleNamespace(
        set_source_frame_paths=lambda paths, status_message=None: calls.append((paths, status_message))
    )
    notebook = _NotebookStub()
    main_window = SimpleNamespace(movie_clips_tab=movie_tab, center_notebook=notebook)

    routed = route_image_to_movie_clips(
        main_window=main_window,
        image_path="C:/tmp/source.png",
        status_message="movie",
    )

    assert notebook.selected is movie_tab
    assert routed == ["C:/tmp/source.png"]
    assert calls == [(["C:/tmp/source.png"], "movie")]
