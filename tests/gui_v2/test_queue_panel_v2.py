"""Tests for PR-203: QueuePanelV2.

Validates:
- Panel instantiation
- Job list display
- Move up/down button states
- Controller method invocation
"""

from __future__ import annotations

import tkinter as tk
from unittest.mock import MagicMock

import pytest

from src.gui.panels_v2.queue_panel_v2 import QueuePanelV2
from src.pipeline.job_models_v2 import QueueJobV2


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
    state.queue_items = []
    return state


class TestQueuePanelV2Instantiation:
    """Tests for panel creation."""

    def test_panel_creates_successfully(self, root, mock_controller, mock_app_state) -> None:
        panel = QueuePanelV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        assert panel is not None

    def test_panel_has_job_listbox(self, root, mock_controller, mock_app_state) -> None:
        panel = QueuePanelV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        assert hasattr(panel, "job_listbox")
        assert isinstance(panel.job_listbox, tk.Listbox)

    def test_panel_has_control_buttons(self, root, mock_controller, mock_app_state) -> None:
        panel = QueuePanelV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        assert hasattr(panel, "move_up_button")
        assert hasattr(panel, "move_down_button")
        assert hasattr(panel, "remove_button")
        assert hasattr(panel, "clear_button")

    def test_panel_has_count_label(self, root, mock_controller, mock_app_state) -> None:
        panel = QueuePanelV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        assert hasattr(panel, "count_label")


class TestQueuePanelV2JobDisplay:
    """Tests for job list display."""

    def test_update_jobs_empty_list(self, root, mock_controller, mock_app_state) -> None:
        panel = QueuePanelV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        panel.update_jobs([])
        assert panel.job_listbox.size() == 0

    def test_update_jobs_shows_jobs(self, root, mock_controller, mock_app_state) -> None:
        panel = QueuePanelV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        jobs = [
            QueueJobV2.create({"prompt": "test1"}),
            QueueJobV2.create({"prompt": "test2"}),
        ]
        panel.update_jobs(jobs)
        assert panel.job_listbox.size() == 2

    def test_update_jobs_updates_count_label(self, root, mock_controller, mock_app_state) -> None:
        panel = QueuePanelV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        jobs = [QueueJobV2.create({}) for _ in range(3)]
        panel.update_jobs(jobs)
        # Count label should show "3 jobs"
        label_text = panel.count_label.cget("text")
        assert "3" in label_text


class TestQueuePanelV2ButtonStates:
    """Tests for button enable/disable states."""

    def test_buttons_disabled_when_empty(self, root, mock_controller, mock_app_state) -> None:
        panel = QueuePanelV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        panel.update_jobs([])
        # Clear should be disabled when empty
        assert "disabled" in panel.clear_button.state()

    def test_clear_enabled_with_jobs(self, root, mock_controller, mock_app_state) -> None:
        panel = QueuePanelV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        jobs = [QueueJobV2.create({})]
        panel.update_jobs(jobs)
        # Clear should be enabled when jobs exist
        assert "disabled" not in panel.clear_button.state()

    def test_move_up_disabled_at_first_position(self, root, mock_controller, mock_app_state) -> None:
        panel = QueuePanelV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        jobs = [QueueJobV2.create({}) for _ in range(3)]
        panel.update_jobs(jobs)
        panel.job_listbox.selection_set(0)  # Select first
        panel._on_selection_changed()
        assert "disabled" in panel.move_up_button.state()

    def test_move_down_disabled_at_last_position(self, root, mock_controller, mock_app_state) -> None:
        panel = QueuePanelV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        jobs = [QueueJobV2.create({}) for _ in range(3)]
        panel.update_jobs(jobs)
        panel.job_listbox.selection_set(2)  # Select last
        panel._on_selection_changed()
        assert "disabled" in panel.move_down_button.state()


class TestQueuePanelV2ControllerInvocation:
    """Tests for controller method calls."""

    def test_on_clear_calls_controller(self, root, mock_controller, mock_app_state) -> None:
        panel = QueuePanelV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        jobs = [QueueJobV2.create({})]
        panel.update_jobs(jobs)
        panel._on_clear()
        mock_controller.on_queue_clear_v2.assert_called_once()

    def test_on_remove_calls_controller_with_job_id(self, root, mock_controller, mock_app_state) -> None:
        panel = QueuePanelV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        job = QueueJobV2.create({})
        panel.update_jobs([job])
        panel.job_listbox.selection_set(0)
        panel._on_selection_changed()
        panel._on_remove()
        mock_controller.on_queue_remove_job_v2.assert_called_once_with(job.job_id)

    def test_on_move_up_calls_controller_with_job_id(self, root, mock_controller, mock_app_state) -> None:
        panel = QueuePanelV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        jobs = [QueueJobV2.create({}) for _ in range(2)]
        panel.update_jobs(jobs)
        panel.job_listbox.selection_set(1)  # Select second
        panel._on_selection_changed()
        panel._on_move_up()
        mock_controller.on_queue_move_up_v2.assert_called_once_with(jobs[1].job_id)

    def test_on_move_down_calls_controller_with_job_id(self, root, mock_controller, mock_app_state) -> None:
        panel = QueuePanelV2(
            root,
            controller=mock_controller,
            app_state=mock_app_state,
        )
        jobs = [QueueJobV2.create({}) for _ in range(2)]
        panel.update_jobs(jobs)
        panel.job_listbox.selection_set(0)  # Select first
        panel._on_selection_changed()
        panel._on_move_down()
        mock_controller.on_queue_move_down_v2.assert_called_once_with(jobs[0].job_id)
