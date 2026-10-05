from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from src.gui.app_state_v2 import AppStateV2
from src.gui.theme_v2 import BACKGROUND_ELEVATED
from src.gui.view_contracts.pipeline_layout_contract import (
    PRIMARY_CONTROL_MIN_WIDTH,
    WORKSPACE_CENTER_COLUMN_MIN_WIDTH,
    WORKSPACE_LEFT_COLUMN_MIN_WIDTH,
)
from src.gui.view_contracts.window_layout_contract import (
    SCREEN_MARGIN_HEIGHT,
    SCREEN_MARGIN_WIDTH,
    compute_window_layout,
    normalize_saved_geometry,
)
from src.gui.views.learning_tab_frame_v2 import LearningTabFrame
from src.gui.views.movie_clips_tab_frame_v2 import MovieClipsTabFrameV2
from src.gui.views.review_tab_frame_v2 import ReviewTabFrame
from src.gui.views.svd_tab_frame_v2 import SVDTabFrameV2
from src.gui.views.video_workflow_tab_frame_v2 import VideoWorkflowTabFrameV2
from src.services.ui_state_store import UIStateStore


class _StubPipelineController:
    def set_learning_enabled(self, _enabled: bool) -> None:
        return


def test_review_tab_uses_shared_workspace_minimums(tk_root) -> None:
    tab = ReviewTabFrame(tk_root)
    try:
        assert tab._body_frame.columnconfigure(0)["minsize"] == WORKSPACE_LEFT_COLUMN_MIN_WIDTH
        assert tab._body_frame.columnconfigure(1)["minsize"] == WORKSPACE_CENTER_COLUMN_MIN_WIDTH
        assert int(tab._controls_frame.grid_info()["row"]) == 1  # below the body, inside the scrollable workspace
        assert tab.prompt_text.cget("bg") == BACKGROUND_ELEVATED
        assert tab.feedback_notes.cget("bg") == BACKGROUND_ELEVATED
    finally:
        tab.destroy()


def test_learning_tab_uses_shared_workspace_minimums_and_staged_rows(
    tk_root, tmp_path: Path
) -> None:
    state_path = tmp_path / "ui_state.json"
    experiments_root = tmp_path / "experiments"
    store = UIStateStore(state_path)

    with (
        patch("src.gui.views.learning_tab_frame_v2.get_ui_state_store", return_value=store),
        patch(
            "src.gui.views.learning_tab_frame_v2.get_learning_experiments_root",
            return_value=experiments_root,
        ),
    ):
        tab = LearningTabFrame(
            tk_root,
            app_state=AppStateV2(),
            pipeline_controller=_StubPipelineController(),
        )
        try:
            assert str(tab.designed_horizontal_panes.cget("orient")) == "horizontal"
            assert tab.experiment_scroll._vsb.winfo_manager() == "grid"
            assert tab.experiment_panel.master is tab.experiment_scroll.inner
            assert (
                tab._discovered_tab_frame.columnconfigure(0)["minsize"]
                == WORKSPACE_LEFT_COLUMN_MIN_WIDTH
            )
            assert (
                tab._discovered_tab_frame.columnconfigure(1)["minsize"]
                == WORKSPACE_CENTER_COLUMN_MIN_WIDTH
            )
            assert int(tab._staged_action_frame.grid_info()["row"]) == 12
            assert int(tab._staged_derive_frame.grid_info()["row"]) == 13
            assert int(tab._staged_review_frame.grid_info()["row"]) == 14
            assert tab._staged_notes_text.cget("bg") == BACKGROUND_ELEVATED
        finally:
            tab.destroy()


def test_video_workflow_tab_uses_shared_form_minimums_and_themed_text(tk_root) -> None:
    tab = VideoWorkflowTabFrameV2(tk_root)
    try:
        assert tab._body_frame.columnconfigure(0)["minsize"] > 0
        assert tab._body_frame.columnconfigure(1)["minsize"] == PRIMARY_CONTROL_MIN_WIDTH
        assert tab.prompt_text.cget("bg") == BACKGROUND_ELEVATED
        assert tab.negative_prompt_text.cget("bg") == BACKGROUND_ELEVATED
    finally:
        tab.destroy()


def test_svd_and_movie_clips_keep_workspace_and_settings_widths(tk_root) -> None:
    svd_tab = SVDTabFrameV2(tk_root)
    movie_tab = MovieClipsTabFrameV2(tk_root)
    try:
        assert svd_tab._body_frame.columnconfigure(0)["minsize"] == 420
        assert svd_tab._body_frame.columnconfigure(1)["minsize"] == 320
        assert svd_tab._settings_frame.columnconfigure(1)["minsize"] == PRIMARY_CONTROL_MIN_WIDTH

        assert movie_tab._body_frame.columnconfigure(0)["minsize"] == 420
        assert movie_tab._body_frame.columnconfigure(1)["minsize"] == 320
        assert movie_tab._settings_frame.columnconfigure(1)["minsize"] == PRIMARY_CONTROL_MIN_WIDTH
        assert movie_tab.image_list.cget("bg") == BACKGROUND_ELEVATED
    finally:
        movie_tab.destroy()
        svd_tab.destroy()


# --- PR-GUI-100: screen-aware window layout and reachable long-form workspaces ---------------------------------------


@pytest.mark.parametrize("screen", [(1366, 768), (1920, 1080), (2560, 1440), (1024, 600)])
def test_window_layout_always_fits_the_screen(screen) -> None:
    width, height = screen
    layout = compute_window_layout(width, height)

    assert layout.min_width <= layout.width <= width - SCREEN_MARGIN_WIDTH
    assert layout.min_height <= layout.height <= height - SCREEN_MARGIN_HEIGHT
    assert layout.default_geometry == f"{layout.width}x{layout.height}"
    if screen == (2560, 1440):
        assert layout.width < width // 1.3  # no giant blank window on a large display
    if screen == (1920, 1080):
        assert layout.width == 1920 - SCREEN_MARGIN_WIDTH  # measured: the Pipeline columns need ~1896 px


@pytest.mark.parametrize(
    ("saved", "expected"),
    [
        ("1984x1350+10+10", "1342x672+10+10"),  # saved on a bigger display: clamped, not forced oversized
        ("1342x672+0+0", "1342x672+0+0"),  # valid saved geometry restores unchanged
        ("1000x500+50+50", "1280x672+50+50"),  # below the minimum is raised to it
        ("1984x1350", "1342x672"),
        ("1984x1110+-32000+-32000", None),  # off-screen sentinel recovers to the default
        ("1342x672+1360+700", None),  # no longer overlaps this display
        ("not-a-geometry", None),
    ],
)
def test_saved_geometry_is_normalized_for_the_current_screen(saved, expected) -> None:
    assert normalize_saved_geometry(saved, compute_window_layout(1366, 768)) == expected


@pytest.mark.parametrize(
    ("tab_factory", "scroll_attr", "last_control_attr"),
    [
        (ReviewTabFrame, "_workspace_scroll", "reprocess_all_button"),
        (SVDTabFrameV2, "_body_scroll", "animate_btn"),
        (VideoWorkflowTabFrameV2, "_body_scroll", "queue_workflow_button"),
    ],
    ids=["review", "svd", "video_workflow"],
)
def test_long_form_tabs_reach_their_lowest_control_on_a_laptop_viewport(
    tk_root, tab_factory, scroll_attr, last_control_attr
) -> None:
    layout = compute_window_layout(1366, 768)
    tk_root.geometry(f"{layout.width}x{layout.height}+0+0")
    tk_root.deiconify()  # a withdrawn root never realizes its children's sizes
    tab = tab_factory(tk_root)
    try:
        tab.pack(fill="both", expand=True)
        tk_root.update()
        scroll = getattr(tab, scroll_attr)
        control = getattr(tab, last_control_attr)

        assert scroll.has_scroll_overflow(), "the workspace must scroll instead of growing the window"
        assert tk_root.winfo_height() <= layout.screen_height - SCREEN_MARGIN_HEIGHT

        scroll._canvas.yview_moveto(1.0)
        tk_root.update()
        view_top, view_bottom = scroll._canvas.winfo_rooty(), scroll._canvas.winfo_rooty() + scroll._canvas.winfo_height()
        control_top = control.winfo_rooty()
        control_bottom = control_top + control.winfo_height()
        assert control_top >= view_top and control_bottom <= view_bottom + 1, "lowest control must be inside the viewport"
    finally:
        tab.destroy()
        tk_root.withdraw()
