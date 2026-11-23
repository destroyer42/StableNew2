"""PR-VID-STORY-380 B6 (route only): Continue in Storyboard hands a finished clip's job to the Storyboard tab.

The three entry-point buttons (Job History, Recent outputs, Make Video result) are deferred until the Video Workflow
layout work (VID-UX-384) lands; they only need to call this route.
"""

from __future__ import annotations

import pytest

from src.gui.controllers.video_workspace_handoff import route_job_to_storyboard


class _Tab:
    def __init__(self) -> None:
        self.started: list[tuple[str, str | None]] = []

    def start_from_job(self, job_id: str, *, status_message: str | None = None) -> None:
        self.started.append((job_id, status_message))


class _Notebook:
    def __init__(self) -> None:
        self.selected: object = None

    def select(self, tab: object) -> None:
        self.selected = tab


class _Window:
    def __init__(self) -> None:
        self.storyboard_tab = _Tab()
        self.center_notebook = _Notebook()


def test_route_selects_the_tab_and_starts_from_the_job():
    window = _Window()
    route_job_to_storyboard(main_window=window, job_id="job-1")
    assert window.center_notebook.selected is window.storyboard_tab
    assert window.storyboard_tab.started == [("job-1", None)]
    route_job_to_storyboard(
        main_window=window, job_id="job-2", status_message="from Recent outputs"
    )
    assert window.storyboard_tab.started[-1] == ("job-2", "from Recent outputs")


def test_route_refuses_when_the_tab_is_missing():
    class Bare:
        pass

    with pytest.raises(RuntimeError, match="Storyboard tab is not available"):
        route_job_to_storyboard(main_window=Bare(), job_id="job-1")


def test_route_refuses_a_tab_without_job_handoff():
    class Odd:
        storyboard_tab = object()

    with pytest.raises(RuntimeError, match="does not support job handoff"):
        route_job_to_storyboard(main_window=Odd(), job_id="job-1")
