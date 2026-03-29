from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from src.gui.app_state_v2 import AppStateV2
from src.gui.theme_v2 import BACKGROUND_ELEVATED
from src.gui.view_contracts.pipeline_layout_contract import (
    PRIMARY_CONTROL_MIN_WIDTH,
    WORKSPACE_CENTER_COLUMN_MIN_WIDTH,
    WORKSPACE_LEFT_COLUMN_MIN_WIDTH,
    WORKSPACE_RIGHT_COLUMN_MIN_WIDTH,
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
        assert int(tab._controls_frame.grid_info()["row"]) == 3
        assert tab.prompt_text.cget("bg") == BACKGROUND_ELEVATED
        assert tab.feedback_notes.cget("bg") == BACKGROUND_ELEVATED
    finally:
        tab.destroy()


def test_learning_tab_uses_shared_workspace_minimums_and_staged_rows(tk_root, tmp_path: Path) -> None:
    state_path = tmp_path / "ui_state.json"
    experiments_root = tmp_path / "experiments"
    store = UIStateStore(state_path)

    with patch("src.gui.views.learning_tab_frame_v2.get_ui_state_store", return_value=store), patch(
        "src.gui.views.learning_tab_frame_v2.get_learning_experiments_root",
        return_value=experiments_root,
    ):
        tab = LearningTabFrame(
            tk_root,
            app_state=AppStateV2(),
            pipeline_controller=_StubPipelineController(),
        )
        try:
            assert tab.body_frame.columnconfigure(0)["minsize"] == WORKSPACE_LEFT_COLUMN_MIN_WIDTH
            assert tab.body_frame.columnconfigure(1)["minsize"] == WORKSPACE_CENTER_COLUMN_MIN_WIDTH
            assert tab.body_frame.columnconfigure(2)["minsize"] == WORKSPACE_RIGHT_COLUMN_MIN_WIDTH
            assert tab._discovered_tab_frame.columnconfigure(0)["minsize"] == WORKSPACE_LEFT_COLUMN_MIN_WIDTH
            assert tab._discovered_tab_frame.columnconfigure(1)["minsize"] == WORKSPACE_CENTER_COLUMN_MIN_WIDTH
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