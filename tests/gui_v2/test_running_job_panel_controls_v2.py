"""Tests for PR-GUI-F3: Running Job panel controls.

Tests:
- Running job panel renders job summary
- Progress and ETA display
- Pause/Resume button behavior
- Cancel button behavior
- Cancel + Return to Queue button behavior
"""

from __future__ import annotations

import tkinter as tk
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.gui.panels_v2.running_job_panel_v2 import RunningJobPanelV2
from src.pipeline.job_models_v2 import JobStatusV2, QueueJobV2


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
    controller.on_pause_job_v2 = MagicMock()
    controller.on_resume_job_v2 = MagicMock()
    controller.on_cancel_job_v2 = MagicMock()
    controller.on_cancel_job_and_return_v2 = MagicMock()
    return controller


@pytest.fixture
def mock_app_state():
    """Create a mock app state."""
    state = MagicMock()
    state.running_job = None
    return state


@pytest.fixture
def sample_running_job():
    """Create a sample running job."""
    job = QueueJobV2.create(
        config_snapshot={"model": "sdxl_base"},
        metadata={"prompt_short": "test prompt"},
    )
    job.status = JobStatusV2.RUNNING
    job.progress = 0.5
    job.eta_seconds = 120
    return job


class TestRunningJobPanelDisplay:
    """Tests for job display rendering."""

    @pytest.mark.gui
    def test_panel_shows_no_job_by_default(self, tk_root, mock_controller, mock_app_state):
        """Panel shows 'No job running' when no job."""
        panel = RunningJobPanelV2(
            tk_root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        assert "No job" in panel.job_info_label.cget("text")

    @pytest.mark.gui
    def test_panel_shows_job_summary(self, tk_root, mock_controller, mock_app_state, sample_running_job):
        """Panel displays job summary when job is running."""
        panel = RunningJobPanelV2(
            tk_root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        panel.update_job(sample_running_job)
        # Should not say "No job"
        assert "No job" not in panel.job_info_label.cget("text")


class TestRunningJobPanelProgress:
    """Tests for progress display."""

    @pytest.mark.gui
    def test_progress_bar_exists(self, tk_root, mock_controller, mock_app_state):
        """Panel has a progress bar."""
        panel = RunningJobPanelV2(
            tk_root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        assert hasattr(panel, "progress_bar")
        assert hasattr(panel, "progress_label")

    @pytest.mark.gui
    def test_progress_updates(self, tk_root, mock_controller, mock_app_state, sample_running_job):
        """Progress bar updates with job progress."""
        panel = RunningJobPanelV2(
            tk_root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        panel.update_job(sample_running_job)
        assert panel.progress_bar["value"] == 50  # 0.5 * 100
        assert "50%" in panel.progress_label.cget("text")

    @pytest.mark.gui
    def test_eta_displays_formatted(self, tk_root, mock_controller, mock_app_state, sample_running_job):
        """ETA is displayed in human-readable format."""
        panel = RunningJobPanelV2(
            tk_root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        panel.update_job(sample_running_job)
        # 120 seconds = 2 minutes
        eta_text = panel.eta_label.cget("text")
        assert "2m" in eta_text or "ETA" in eta_text


class TestRunningJobPanelButtons:
    """Tests for control buttons."""

    @pytest.mark.gui
    def test_all_buttons_exist(self, tk_root, mock_controller, mock_app_state):
        """Panel has all required control buttons."""
        panel = RunningJobPanelV2(
            tk_root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        assert hasattr(panel, "pause_resume_button")
        assert hasattr(panel, "cancel_button")
        assert hasattr(panel, "cancel_return_button")

    @pytest.mark.gui
    def test_buttons_disabled_when_no_job(self, tk_root, mock_controller, mock_app_state):
        """Buttons are disabled when no job is running."""
        panel = RunningJobPanelV2(
            tk_root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        panel.update_job(None)
        assert "disabled" in panel.pause_resume_button.state()
        assert "disabled" in panel.cancel_button.state()
        assert "disabled" in panel.cancel_return_button.state()

    @pytest.mark.gui
    def test_buttons_enabled_when_job_running(self, tk_root, mock_controller, mock_app_state, sample_running_job):
        """Buttons are enabled when job is running."""
        panel = RunningJobPanelV2(
            tk_root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        panel.update_job(sample_running_job)
        assert "disabled" not in panel.pause_resume_button.state()
        assert "disabled" not in panel.cancel_button.state()
        assert "disabled" not in panel.cancel_return_button.state()


class TestRunningJobPanelCallbacks:
    """Tests for button callbacks."""

    @pytest.mark.gui
    def test_pause_calls_controller(self, tk_root, mock_controller, mock_app_state, sample_running_job):
        """Pause button calls controller pause method."""
        panel = RunningJobPanelV2(
            tk_root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        panel.update_job(sample_running_job)
        panel._on_pause_resume()
        mock_controller.on_pause_job_v2.assert_called_once()

    @pytest.mark.gui
    def test_resume_calls_controller_when_paused(self, tk_root, mock_controller, mock_app_state, sample_running_job):
        """Resume button calls controller resume method when paused."""
        sample_running_job.status = JobStatusV2.PAUSED
        panel = RunningJobPanelV2(
            tk_root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        panel.update_job(sample_running_job)
        panel._on_pause_resume()
        mock_controller.on_resume_job_v2.assert_called_once()

    @pytest.mark.gui
    def test_cancel_calls_controller(self, tk_root, mock_controller, mock_app_state, sample_running_job):
        """Cancel button calls controller cancel method."""
        panel = RunningJobPanelV2(
            tk_root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        panel.update_job(sample_running_job)
        panel._on_cancel()
        mock_controller.on_cancel_job_v2.assert_called_once()

    @pytest.mark.gui
    def test_cancel_and_return_calls_controller(self, tk_root, mock_controller, mock_app_state, sample_running_job):
        """Cancel + Return button calls controller method."""
        panel = RunningJobPanelV2(
            tk_root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        panel.update_job(sample_running_job)
        panel._on_cancel_and_return()
        mock_controller.on_cancel_job_and_return_v2.assert_called_once()


class TestRunningJobPanelPauseResumeToggle:
    """Tests for pause/resume button text toggle."""

    @pytest.mark.gui
    def test_button_says_pause_when_running(self, tk_root, mock_controller, mock_app_state, sample_running_job):
        """Button says 'Pause' when job is running."""
        panel = RunningJobPanelV2(
            tk_root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        panel.update_job(sample_running_job)
        assert "Pause" in panel.pause_resume_button.cget("text")

    @pytest.mark.gui
    def test_button_says_resume_when_paused(self, tk_root, mock_controller, mock_app_state, sample_running_job):
        """Button says 'Resume' when job is paused."""
        sample_running_job.status = JobStatusV2.PAUSED
        panel = RunningJobPanelV2(
            tk_root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        panel.update_job(sample_running_job)
        assert "Resume" in panel.pause_resume_button.cget("text")
