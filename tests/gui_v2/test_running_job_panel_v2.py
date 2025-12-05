"""Tests for PR-203: RunningJobPanelV2.

Validates:
- Panel instantiation
- Job info display
- Progress bar updates
- ETA formatting
- Pause/Resume/Cancel button behavior
"""

from __future__ import annotations

import tkinter as tk
from unittest.mock import MagicMock

import pytest

from src.gui.panels_v2.running_job_panel_v2 import RunningJobPanelV2
from src.pipeline.job_models_v2 import JobStatusV2, QueueJobV2


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
    """Create a mock app state."""
    state = MagicMock()
    state.running_job = None
    return state


class TestRunningJobPanelV2Instantiation:
    """Tests for panel creation."""

    def test_panel_creates_successfully(self, root, mock_controller, mock_app_state) -> None:
        panel = RunningJobPanelV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        assert panel is not None

    def test_panel_has_progress_bar(self, root, mock_controller, mock_app_state) -> None:
        panel = RunningJobPanelV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        assert hasattr(panel, "progress_bar")

    def test_panel_has_control_buttons(self, root, mock_controller, mock_app_state) -> None:
        panel = RunningJobPanelV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        assert hasattr(panel, "pause_resume_button")
        assert hasattr(panel, "cancel_button")

    def test_panel_has_status_label(self, root, mock_controller, mock_app_state) -> None:
        panel = RunningJobPanelV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        assert hasattr(panel, "status_label")

    def test_panel_has_eta_label(self, root, mock_controller, mock_app_state) -> None:
        panel = RunningJobPanelV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        assert hasattr(panel, "eta_label")


class TestRunningJobPanelV2Display:
    """Tests for job display."""

    def test_no_job_shows_idle(self, root, mock_controller, mock_app_state) -> None:
        panel = RunningJobPanelV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        panel.update_job(None)
        label_text = panel.job_info_label.cget("text")
        assert "No job" in label_text

    def test_update_job_shows_job_info(self, root, mock_controller, mock_app_state) -> None:
        panel = RunningJobPanelV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        job = QueueJobV2.create({"prompt": "test prompt"})
        job.status = JobStatusV2.RUNNING
        panel.update_job(job)
        # Job info should be displayed
        label_text = panel.job_info_label.cget("text")
        assert label_text != "No job running"

    def test_update_job_shows_progress(self, root, mock_controller, mock_app_state) -> None:
        panel = RunningJobPanelV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        job = QueueJobV2.create({})
        job.status = JobStatusV2.RUNNING
        job.progress = 0.5
        panel.update_job(job)
        # Progress label should show 50%
        progress_text = panel.progress_label.cget("text")
        assert "50" in progress_text


class TestRunningJobPanelV2Progress:
    """Tests for progress updates."""

    def test_update_progress_changes_bar(self, root, mock_controller, mock_app_state) -> None:
        panel = RunningJobPanelV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        job = QueueJobV2.create({})
        job.status = JobStatusV2.RUNNING
        panel.update_job(job)
        panel.update_progress(0.75)
        assert panel.progress_bar.cget("value") == 75

    def test_update_progress_changes_label(self, root, mock_controller, mock_app_state) -> None:
        panel = RunningJobPanelV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        job = QueueJobV2.create({})
        job.status = JobStatusV2.RUNNING
        panel.update_job(job)
        panel.update_progress(0.33)
        progress_text = panel.progress_label.cget("text")
        assert "33" in progress_text


class TestRunningJobPanelV2ETA:
    """Tests for ETA formatting."""

    def test_format_eta_seconds(self, root, mock_controller, mock_app_state) -> None:
        panel = RunningJobPanelV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        result = panel._format_eta(45)
        assert "45s" in result

    def test_format_eta_minutes(self, root, mock_controller, mock_app_state) -> None:
        panel = RunningJobPanelV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        result = panel._format_eta(125)  # 2m 5s
        assert "2m" in result

    def test_format_eta_hours(self, root, mock_controller, mock_app_state) -> None:
        panel = RunningJobPanelV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        result = panel._format_eta(3700)  # 1h 1m
        assert "1h" in result

    def test_format_eta_none_returns_empty(self, root, mock_controller, mock_app_state) -> None:
        panel = RunningJobPanelV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        result = panel._format_eta(None)
        assert result == ""

    def test_format_eta_zero_returns_empty(self, root, mock_controller, mock_app_state) -> None:
        panel = RunningJobPanelV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        result = panel._format_eta(0)
        assert result == ""


class TestRunningJobPanelV2ButtonStates:
    """Tests for button enable/disable states."""

    def test_buttons_disabled_when_no_job(self, root, mock_controller, mock_app_state) -> None:
        panel = RunningJobPanelV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        panel.update_job(None)
        assert "disabled" in panel.pause_resume_button.state()
        assert "disabled" in panel.cancel_button.state()

    def test_buttons_enabled_when_running(self, root, mock_controller, mock_app_state) -> None:
        panel = RunningJobPanelV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        job = QueueJobV2.create({})
        job.status = JobStatusV2.RUNNING
        panel.update_job(job)
        assert "disabled" not in panel.pause_resume_button.state()
        assert "disabled" not in panel.cancel_button.state()

    def test_pause_button_text_when_running(self, root, mock_controller, mock_app_state) -> None:
        panel = RunningJobPanelV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        job = QueueJobV2.create({})
        job.status = JobStatusV2.RUNNING
        panel.update_job(job)
        button_text = panel.pause_resume_button.cget("text")
        assert button_text == "Pause"

    def test_resume_button_text_when_paused(self, root, mock_controller, mock_app_state) -> None:
        panel = RunningJobPanelV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        job = QueueJobV2.create({})
        job.status = JobStatusV2.PAUSED
        panel.update_job(job)
        button_text = panel.pause_resume_button.cget("text")
        assert button_text == "Resume"


class TestRunningJobPanelV2ControllerInvocation:
    """Tests for controller method calls."""

    def test_pause_calls_controller_when_running(self, root, mock_controller, mock_app_state) -> None:
        panel = RunningJobPanelV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        job = QueueJobV2.create({})
        job.status = JobStatusV2.RUNNING
        panel.update_job(job)
        panel._on_pause_resume()
        mock_controller.on_pause_job_v2.assert_called_once()

    def test_resume_calls_controller_when_paused(self, root, mock_controller, mock_app_state) -> None:
        panel = RunningJobPanelV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        job = QueueJobV2.create({})
        job.status = JobStatusV2.PAUSED
        panel.update_job(job)
        panel._on_pause_resume()
        mock_controller.on_resume_job_v2.assert_called_once()

    def test_cancel_calls_controller(self, root, mock_controller, mock_app_state) -> None:
        panel = RunningJobPanelV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        job = QueueJobV2.create({})
        job.status = JobStatusV2.RUNNING
        panel.update_job(job)
        panel._on_cancel()
        mock_controller.on_cancel_job_v2.assert_called_once()
