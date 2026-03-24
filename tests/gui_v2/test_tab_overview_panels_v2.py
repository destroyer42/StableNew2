from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import tkinter as tk

from src.gui.app_state_v2 import AppStateV2
from src.gui.views.learning_tab_frame_v2 import LearningTabFrame
from src.gui.views.movie_clips_tab_frame_v2 import MovieClipsTabFrameV2
from src.gui.views.pipeline_tab_frame_v2 import PipelineTabFrame
from src.gui.views.review_tab_frame_v2 import ReviewTabFrame
from src.gui.views.svd_tab_frame_v2 import SVDTabFrameV2
from src.gui.views.video_workflow_tab_frame_v2 import VideoWorkflowTabFrameV2
from src.gui.widgets.tab_overview_panel_v2 import TabOverviewPanel, get_tab_overview_content
from src.services.ui_state_store import UIStateStore


class _StubPipelineController:
    def set_learning_enabled(self, _enabled: bool) -> None:
        return


def test_tab_overview_panel_defaults_to_compact_state(tk_root: tk.Tk) -> None:
    panel = TabOverviewPanel(tk_root, content=get_tab_overview_content("pipeline"))
    try:
        assert panel.title_label.cget("text") == "About This Tab: Pipeline"
        assert panel.is_expanded() is False
        assert panel.toggle_button.cget("text") == "Show Details"
        panel.toggle_button.invoke()
        assert panel.is_expanded() is True
        assert "Purpose:" in panel.details_label.cget("text")
    finally:
        panel.destroy()


def test_pipeline_tab_exposes_overview_panel(tk_root: tk.Tk) -> None:
    tab = PipelineTabFrame(tk_root, app_state=AppStateV2())
    try:
        assert isinstance(tab.overview_panel, TabOverviewPanel)
        assert tab.overview_panel.content.tab_id == "pipeline"
        assert tab.overview_panel.content.tab_name == "Pipeline"
        assert "queue-first workspace" in tab.overview_panel.details_label.cget("text").lower()
    finally:
        tab.destroy()


def test_review_tab_exposes_overview_panel(tk_root: tk.Tk) -> None:
    tab = ReviewTabFrame(tk_root)
    try:
        assert isinstance(tab.overview_panel, TabOverviewPanel)
        assert tab.overview_panel.content.tab_id == "review"
        assert tab.overview_panel.content.tab_name == "Review"
        assert "advanced reprocess workspace" in tab.overview_panel.details_label.cget("text").lower()
    finally:
        tab.destroy()


def test_learning_tab_exposes_overview_panel(tk_root: tk.Tk, tmp_path: Path) -> None:
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
            assert isinstance(tab.overview_panel, TabOverviewPanel)
            assert tab.overview_panel.content.tab_id == "learning"
            assert "evidence-and-experiment" in tab.overview_panel.details_label.cget("text").lower()
        finally:
            tab.destroy()


def test_svd_tab_exposes_overview_panel(tk_root: tk.Tk) -> None:
    tab = SVDTabFrameV2(tk_root)
    try:
        assert isinstance(tab.overview_panel, TabOverviewPanel)
        assert tab.overview_panel.content.tab_id == "svd"
        assert "native svd clip" in tab.overview_panel.summary_label.cget("text").lower()
    finally:
        tab.destroy()


def test_video_workflow_tab_exposes_overview_panel(tk_root: tk.Tk) -> None:
    tab = VideoWorkflowTabFrameV2(tk_root)
    try:
        assert isinstance(tab.overview_panel, TabOverviewPanel)
        assert tab.overview_panel.content.tab_id == "video_workflow"
        assert "workflow-driven video" in tab.overview_panel.summary_label.cget("text").lower()
    finally:
        tab.destroy()


def test_movie_clips_tab_exposes_overview_panel(tk_root: tk.Tk) -> None:
    tab = MovieClipsTabFrameV2(tk_root)
    try:
        assert isinstance(tab.overview_panel, TabOverviewPanel)
        assert tab.overview_panel.content.tab_id == "movie_clips"
        assert "ordered list of images" in tab.overview_panel.summary_label.cget("text").lower()
    finally:
        tab.destroy()