"""Tests for PR-203: PipelineRunControlsV2 (simplified version).

NOTE: PR-GUI-F1 removed PipelineRunControlsV2 from the layout.
Queue controls are now in QueuePanelV2.
These tests are marked as skip.
"""

from __future__ import annotations

import tkinter as tk
from unittest.mock import MagicMock

import pytest

# PR-GUI-F1: PipelineRunControlsV2 removed from layout, buttons moved to QueuePanelV2
pytestmark = pytest.mark.skip(reason="PR-GUI-F1: PipelineRunControlsV2 removed from layout")

from src.gui.panels_v2.pipeline_run_controls_v2 import PipelineRunControlsV2


@pytest.fixture
def root():
    """Create a Tk root for testing."""
    root = tk.Tk()
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def mock_controller():
    """Create a mock controller."""
    controller = MagicMock()
    return controller


@pytest.fixture
def mock_app_state():
    """Create a mock app state with PR-203 attributes."""
    state = MagicMock()
    state.is_queue_paused = False
    state.auto_run_queue = False
    state.running_job = None
    state.queue_items = []
    state.current_pack = "test_pack"
    return state


class TestPipelineRunControlsV2Instantiation:
    """Tests for panel creation."""

    def test_panel_creates_successfully(self, root, mock_controller, mock_app_state) -> None:
        panel = PipelineRunControlsV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        assert panel is not None

    def test_panel_has_add_button(self, root, mock_controller, mock_app_state) -> None:
        panel = PipelineRunControlsV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        assert hasattr(panel, "add_button")

    def test_panel_has_clear_draft_button(self, root, mock_controller, mock_app_state) -> None:
        panel = PipelineRunControlsV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        assert hasattr(panel, "clear_draft_button")

    def test_panel_has_auto_run_checkbox(self, root, mock_controller, mock_app_state) -> None:
        panel = PipelineRunControlsV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        assert hasattr(panel, "auto_run_check")
        assert hasattr(panel, "auto_run_var")

    def test_panel_has_pause_resume_button(self, root, mock_controller, mock_app_state) -> None:
        panel = PipelineRunControlsV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        assert hasattr(panel, "pause_resume_button")

    def test_panel_has_status_label(self, root, mock_controller, mock_app_state) -> None:
        panel = PipelineRunControlsV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        assert hasattr(panel, "status_label")


class TestPipelineRunControlsV2NoLegacyControls:
    """Tests to verify legacy controls are removed (PR-203)."""

    def test_no_mode_label(self, root, mock_controller, mock_app_state) -> None:
        """PR-203: Mode label should not exist."""
        panel = PipelineRunControlsV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        assert not hasattr(panel, "mode_label")

    def test_no_run_now_button(self, root, mock_controller, mock_app_state) -> None:
        """PR-203: Run Now button should not exist."""
        panel = PipelineRunControlsV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        assert not hasattr(panel, "run_now_button")

    def test_no_run_button(self, root, mock_controller, mock_app_state) -> None:
        """PR-203: Run button should not exist."""
        panel = PipelineRunControlsV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        assert not hasattr(panel, "run_button")

    def test_no_stop_button(self, root, mock_controller, mock_app_state) -> None:
        """PR-203: Stop button should not exist (moved to RunningJobPanelV2)."""
        panel = PipelineRunControlsV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        assert not hasattr(panel, "stop_button")


class TestPipelineRunControlsV2StateUpdate:
    """Tests for state updates."""

    def test_update_shows_queue_paused_status(self, root, mock_controller, mock_app_state) -> None:
        panel = PipelineRunControlsV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        mock_app_state.is_queue_paused = True
        mock_app_state.queue_items = ["job1", "job2"]
        panel.update_from_app_state(mock_app_state)
        status_text = panel.status_label.cget("text")
        assert "Paused" in status_text

    def test_update_shows_running_status(self, root, mock_controller, mock_app_state) -> None:
        panel = PipelineRunControlsV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        mock_app_state.running_job = {"job_id": "test"}
        panel.update_from_app_state(mock_app_state)
        status_text = panel.status_label.cget("text")
        assert "Running" in status_text

    def test_update_shows_pending_count(self, root, mock_controller, mock_app_state) -> None:
        panel = PipelineRunControlsV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        mock_app_state.queue_items = ["job1", "job2", "job3"]
        panel.update_from_app_state(mock_app_state)
        status_text = panel.status_label.cget("text")
        assert "3" in status_text

    def test_pause_button_text_when_running(self, root, mock_controller, mock_app_state) -> None:
        panel = PipelineRunControlsV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        mock_app_state.is_queue_paused = False
        panel.update_from_app_state(mock_app_state)
        button_text = panel.pause_resume_button.cget("text")
        assert "Pause" in button_text

    def test_resume_button_text_when_paused(self, root, mock_controller, mock_app_state) -> None:
        panel = PipelineRunControlsV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        mock_app_state.is_queue_paused = True
        panel.update_from_app_state(mock_app_state)
        button_text = panel.pause_resume_button.cget("text")
        assert "Resume" in button_text

    def test_auto_run_checkbox_reflects_state(self, root, mock_controller, mock_app_state) -> None:
        panel = PipelineRunControlsV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        mock_app_state.auto_run_queue = True
        panel.update_from_app_state(mock_app_state)
        assert panel.auto_run_var.get() is True


class TestPipelineRunControlsV2ControllerInvocation:
    """Tests for controller method calls."""

    def test_add_to_queue_calls_controller(self, root, mock_controller, mock_app_state) -> None:
        panel = PipelineRunControlsV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        panel._on_add_to_queue()
        mock_controller.on_add_job_to_queue_v2.assert_called_once()

    def test_clear_draft_calls_controller(self, root, mock_controller, mock_app_state) -> None:
        panel = PipelineRunControlsV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        panel._on_clear_draft()
        mock_controller.on_clear_job_draft.assert_called_once()

    def test_pause_calls_controller(self, root, mock_controller, mock_app_state) -> None:
        panel = PipelineRunControlsV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        panel._is_queue_paused = False
        panel._on_pause_resume()
        mock_controller.on_pause_queue_v2.assert_called_once()

    def test_resume_calls_controller(self, root, mock_controller, mock_app_state) -> None:
        panel = PipelineRunControlsV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        panel._is_queue_paused = True
        panel._on_pause_resume()
        mock_controller.on_resume_queue_v2.assert_called_once()

    def test_auto_run_changed_calls_controller(self, root, mock_controller, mock_app_state) -> None:
        panel = PipelineRunControlsV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        panel.auto_run_var.set(True)
        panel._on_auto_run_changed()
        mock_controller.on_set_auto_run_v2.assert_called_once_with(True)


class TestPipelineRunControlsV2ButtonStates:
    """Tests for button enable/disable states."""

    def test_add_disabled_without_pack(self, root, mock_controller, mock_app_state) -> None:
        panel = PipelineRunControlsV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        mock_app_state.current_pack = None
        panel.update_from_app_state(mock_app_state)
        assert "disabled" in panel.add_button.state()

    def test_add_enabled_with_pack(self, root, mock_controller, mock_app_state) -> None:
        panel = PipelineRunControlsV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        mock_app_state.current_pack = "test_pack"
        panel.update_from_app_state(mock_app_state)
        assert "disabled" not in panel.add_button.state()

    def test_clear_draft_always_enabled(self, root, mock_controller, mock_app_state) -> None:
        panel = PipelineRunControlsV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        panel.update_from_app_state(mock_app_state)
        assert "disabled" not in panel.clear_draft_button.state()
