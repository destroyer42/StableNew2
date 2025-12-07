"""Tests for PR-GUI-F3: Queue panel auto-run and send job controls.

Tests:
- Auto-run checkbox reflects state and updates via callback
- Pause/Resume button text flips correctly
- Send Job button disabled when queue empty
- Send Job invokes correct callback when enabled
"""

from __future__ import annotations

import tkinter as tk
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.gui.panels_v2.queue_panel_v2 import QueuePanelV2
from src.pipeline.job_models_v2 import QueueJobV2


@pytest.fixture
def tk_root():
    """Create a Tk root or skip if not available."""
    try:
        root = tk.Tk()
    except tk.TclError as e:
        pytest.skip(f"Tk not available: {e}")
    root.withdraw()
    yield root
    try:
        root.destroy()
    except Exception:
        pass


@pytest.fixture
def mock_controller():
    """Create a mock controller with required methods."""
    controller = MagicMock()
    controller.on_set_auto_run_v2 = MagicMock()
    controller.on_pause_queue_v2 = MagicMock()
    controller.on_resume_queue_v2 = MagicMock()
    controller.on_queue_send_job_v2 = MagicMock()
    return controller


@pytest.fixture
def mock_app_state():
    """Create a mock app state."""
    state = MagicMock()
    state.queue_items = []
    state.is_queue_paused = False
    state.auto_run_queue = False
    state.running_job = None
    return state


class TestQueuePanelAutoRunCheckbox:
    """Tests for auto-run checkbox behavior."""

    @pytest.mark.gui
    def test_auto_run_checkbox_exists(self, tk_root, mock_controller, mock_app_state):
        """Panel has an auto-run checkbox."""
        panel = QueuePanelV2(
            tk_root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        assert hasattr(panel, "auto_run_check")
        assert hasattr(panel, "auto_run_var")

    @pytest.mark.gui
    def test_auto_run_checkbox_reflects_state(self, tk_root, mock_controller, mock_app_state):
        """Auto-run checkbox reflects app state value."""
        mock_app_state.auto_run_queue = True
        panel = QueuePanelV2(
            tk_root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        panel.update_from_app_state(mock_app_state)
        assert panel.auto_run_var.get() is True

    @pytest.mark.gui
    def test_auto_run_toggle_calls_controller(self, tk_root, mock_controller, mock_app_state):
        """Toggling auto-run calls controller method."""
        panel = QueuePanelV2(
            tk_root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        panel.auto_run_var.set(True)
        panel._on_auto_run_changed()
        mock_controller.on_set_auto_run_v2.assert_called_once_with(True)


class TestQueuePanelPauseResumeButton:
    """Tests for pause/resume button behavior."""

    @pytest.mark.gui
    def test_pause_resume_button_exists(self, tk_root, mock_controller, mock_app_state):
        """Panel has a pause/resume button."""
        panel = QueuePanelV2(
            tk_root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        assert hasattr(panel, "pause_resume_button")

    @pytest.mark.gui
    def test_pause_resume_button_text_flips(self, tk_root, mock_controller, mock_app_state):
        """Pause/resume button text changes based on state."""
        panel = QueuePanelV2(
            tk_root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        
        # Not paused - should say "Pause Queue"
        mock_app_state.is_queue_paused = False
        panel.update_from_app_state(mock_app_state)
        assert "Pause" in panel.pause_resume_button.cget("text")
        
        # Paused - should say "Resume Queue"
        mock_app_state.is_queue_paused = True
        panel.update_from_app_state(mock_app_state)
        assert "Resume" in panel.pause_resume_button.cget("text")

    @pytest.mark.gui
    def test_pause_calls_controller_pause(self, tk_root, mock_controller, mock_app_state):
        """Clicking pause when not paused calls pause method."""
        panel = QueuePanelV2(
            tk_root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        panel._is_queue_paused = False
        panel._on_pause_resume()
        mock_controller.on_pause_queue_v2.assert_called_once()

    @pytest.mark.gui
    def test_resume_calls_controller_resume(self, tk_root, mock_controller, mock_app_state):
        """Clicking resume when paused calls resume method."""
        panel = QueuePanelV2(
            tk_root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        panel._is_queue_paused = True
        panel._on_pause_resume()
        mock_controller.on_resume_queue_v2.assert_called_once()


class TestQueuePanelSendJobButton:
    """Tests for Send Job button behavior."""

    @pytest.mark.gui
    def test_send_job_button_exists(self, tk_root, mock_controller, mock_app_state):
        """Panel has a Send Job button."""
        panel = QueuePanelV2(
            tk_root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        assert hasattr(panel, "send_job_button")

    @pytest.mark.gui
    def test_send_job_disabled_when_queue_empty(self, tk_root, mock_controller, mock_app_state):
        """Send Job button is disabled when queue is empty."""
        panel = QueuePanelV2(
            tk_root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        panel._jobs = []
        panel._update_button_states()
        assert "disabled" in panel.send_job_button.state()

    @pytest.mark.gui
    def test_send_job_enabled_when_queue_has_jobs(self, tk_root, mock_controller, mock_app_state):
        """Send Job button is enabled when queue has jobs."""
        panel = QueuePanelV2(
            tk_root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        mock_job = MagicMock(spec=QueueJobV2)
        mock_job.job_id = "test-job"
        panel._jobs = [mock_job]
        panel._update_button_states()
        assert "disabled" not in panel.send_job_button.state()

    @pytest.mark.gui
    def test_send_job_calls_controller(self, tk_root, mock_controller, mock_app_state):
        """Send Job button invokes controller method."""
        panel = QueuePanelV2(
            tk_root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        panel._on_send_job()
        mock_controller.on_queue_send_job_v2.assert_called_once()


class TestQueuePanelStatusLabel:
    """Tests for queue status label."""

    @pytest.mark.gui
    def test_status_label_exists(self, tk_root, mock_controller, mock_app_state):
        """Panel has a queue status label."""
        panel = QueuePanelV2(
            tk_root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        assert hasattr(panel, "queue_status_label")

    @pytest.mark.gui
    def test_status_label_shows_idle(self, tk_root, mock_controller, mock_app_state):
        """Status label shows idle when no jobs."""
        panel = QueuePanelV2(
            tk_root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        panel._update_queue_status_display(
            is_paused=False,
            running_job=None,
            queue_count=0,
        )
        assert "Idle" in panel.queue_status_label.cget("text")

    @pytest.mark.gui
    def test_status_label_shows_paused(self, tk_root, mock_controller, mock_app_state):
        """Status label shows paused state."""
        panel = QueuePanelV2(
            tk_root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        panel._update_queue_status_display(
            is_paused=True,
            running_job=None,
            queue_count=3,
        )
        assert "Paused" in panel.queue_status_label.cget("text")
