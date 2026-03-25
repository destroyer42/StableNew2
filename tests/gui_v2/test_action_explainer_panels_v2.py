from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from src.gui.app_state_v2 import AppStateV2
from src.gui.panels_v2.queue_panel_v2 import QueuePanelV2
from src.gui.views.learning_tab_frame_v2 import LearningTabFrame
from src.gui.views.movie_clips_tab_frame_v2 import MovieClipsTabFrameV2
from src.gui.views.review_tab_frame_v2 import ReviewTabFrame
from src.gui.views.svd_tab_frame_v2 import SVDTabFrameV2
from src.gui.views.video_workflow_tab_frame_v2 import VideoWorkflowTabFrameV2
from src.gui.widgets.action_explainer_panel_v2 import ActionExplainerContent, ActionExplainerPanel
from src.services.ui_state_store import UIStateStore


class _StubPipelineController:
    def set_learning_enabled(self, _enabled: bool) -> None:
        return


def test_action_explainer_panel_renders_summary_and_bullets(tk_root) -> None:
    panel = ActionExplainerPanel(
        tk_root,
        content=ActionExplainerContent(
            title="Test Actions",
            summary="Choose the safe path before you click.",
            bullets=("First action", "Second action"),
        ),
    )
    try:
        assert panel.title_label.cget("text") == "Test Actions"
        assert panel.is_expanded() is False
        assert panel.toggle_button.cget("text") == "Show Guidance"
        assert "safe path" in panel.summary_label.cget("text").lower()
        assert "- First action" in panel.details_label.cget("text")
        panel.toggle_button.invoke()
        assert panel.is_expanded() is True
        assert panel.toggle_button.cget("text") == "Hide Guidance"
    finally:
        panel.destroy()


def test_action_explainer_panel_expands_with_help_mode(tk_root) -> None:
    app_state = AppStateV2()
    panel = ActionExplainerPanel(
        tk_root,
        content=ActionExplainerContent(
            title="Test Actions",
            summary="Choose the safe path before you click.",
            bullets=("First action",),
        ),
        app_state=app_state,
    )
    try:
        assert panel.is_expanded() is False
        app_state.set_help_mode_enabled(True)
        assert panel.is_expanded() is True
        assert panel.toggle_button.cget("text") == "Help Mode On"
        assert str(panel.toggle_button.cget("state")) == "disabled"
    finally:
        panel.destroy()


def test_queue_panel_exposes_action_help_panel(tk_root) -> None:
    panel = QueuePanelV2(tk_root, app_state=AppStateV2())
    try:
        assert isinstance(panel.queue_action_help_panel, ActionExplainerPanel)
        assert "every job runs through the queue" in panel.queue_action_help_panel.summary_label.cget("text").lower()
        assert "manually dispatches only the current top queued job" in panel.queue_action_help_panel.details_label.cget("text").lower()
    finally:
        panel.destroy()


def test_review_tab_exposes_action_help_and_tooltips(tk_root) -> None:
    tab = ReviewTabFrame(tk_root)
    try:
        assert isinstance(tab.action_help_panel, ActionExplainerPanel)
        assert "metadata-aware decisions" in tab.action_help_panel.summary_label.cget("text").lower()
        assert "use learning" in tab.action_help_panel.summary_label.cget("text").lower()
        assert "does not queue a new reprocess job" in tab.import_selected_tooltip.text.lower()
        assert "queue every loaded image" in tab.reprocess_all_button.tooltip.text.lower()
    finally:
        tab.destroy()


def test_learning_tab_exposes_staged_queue_and_review_help(tk_root, tmp_path: Path) -> None:
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
            assert isinstance(tab.discovered_help_panel, ActionExplainerPanel)
            assert "discovered review inbox" in tab.discovered_help_panel.summary_label.cget("text").lower()
            assert isinstance(tab.staged_queue_help_panel, ActionExplainerPanel)
            assert isinstance(tab.staged_review_help_panel, ActionExplainerPanel)
            assert "queue now for bulk stage submission" in tab.staged_queue_help_panel.summary_label.cget("text").lower()
            assert "custom edits before queueing" in tab._staged_review_buttons["refine"].tooltip.text.lower()
        finally:
            tab.destroy()


def test_svd_tab_exposes_workflow_help_and_tooltips(tk_root) -> None:
    tab = SVDTabFrameV2(tk_root)
    try:
        assert isinstance(tab.workflow_help_panel, ActionExplainerPanel)
        assert "choose svd when you have one strong still image" in tab.workflow_help_panel.summary_label.cget("text").lower()
        assert "secondary motion" in tab.workflow_help_panel.summary_label.cget("text").lower()
        assert "does not queue a job yet" in tab.use_latest_output_tooltip.text.lower()
        assert "queue a native svd animation job" in tab.animate_tooltip.text.lower()
    finally:
        tab.destroy()


def test_video_workflow_tab_exposes_workflow_help_and_queue_tooltip(tk_root) -> None:
    tab = VideoWorkflowTabFrameV2(tk_root)
    try:
        assert isinstance(tab.workflow_help_panel, ActionExplainerPanel)
        assert "secondary motion" in tab.workflow_help_panel.summary_label.cget("text").lower()
        assert "does not queue the workflow yet" in tab.use_latest_output_tooltip.text.lower()
        assert "queue a workflow-driven video job" in tab.queue_workflow_tooltip.text.lower()
    finally:
        tab.destroy()


def test_movie_clips_tab_exposes_workflow_help_and_build_tooltip(tk_root) -> None:
    tab = MovieClipsTabFrameV2(tk_root)
    try:
        assert isinstance(tab.workflow_help_panel, ActionExplainerPanel)
        assert "generate new motion" in tab.workflow_help_panel.summary_label.cget("text").lower()
        assert "video-output bundle" in tab.latest_video_tooltip.text.lower()
        assert "assemble the currently ordered image list" in tab.build_tooltip.text.lower()
    finally:
        tab.destroy()