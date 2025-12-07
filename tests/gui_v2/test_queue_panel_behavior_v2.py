"""Tests for PR-GUI-F2: Queue Panel Behavior.

Validates:
- Selection tracks selected job ID
- Move buttons call callbacks with correct ID
- Clear queue button calls callback without selection
- Running job card updates labels
- Running job row highlighted when present
- Order numbers displayed in queue list
"""

from __future__ import annotations

import tkinter as tk
from unittest.mock import MagicMock

import pytest

from src.gui.panels_v2.queue_panel_v2 import QueuePanelV2
from src.gui.panels_v2.running_job_panel_v2 import RunningJobPanelV2
from src.pipeline.job_models_v2 import JobStatusV2, QueueJobV2


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def tk_root():
    """Create a Tk root for testing."""
    try:
        root = tk.Tk()
        root.withdraw()
        yield root
        root.destroy()
    except tk.TclError as exc:
        pytest.skip(f"Tkinter not available: {exc}")


@pytest.fixture
def mock_controller():
    """Create a mock controller with queue operation methods."""
    controller = MagicMock()
    controller.on_queue_move_up_v2 = MagicMock()
    controller.on_queue_move_down_v2 = MagicMock()
    controller.on_queue_remove_job_v2 = MagicMock()
    controller.on_queue_clear_v2 = MagicMock()
    return controller


@pytest.fixture
def mock_app_state():
    """Create a mock app state."""
    state = MagicMock()
    state.queue_items = []
    state.running_job = None
    state.is_queue_paused = False
    state.auto_run_queue = False
    return state


def create_test_jobs(count: int = 3) -> list[QueueJobV2]:
    """Create test QueueJobV2 instances."""
    jobs = []
    for i in range(count):
        job = QueueJobV2.create(
            config_snapshot={"prompt": f"test prompt {i}", "model": f"model_{i}"},
            metadata={"variant_index": i, "variant_total": count},
        )
        job.job_id = f"test_job_{i}"  # Use predictable IDs
        jobs.append(job)
    return jobs


# -----------------------------------------------------------------------------
# Queue Panel Selection Tests
# -----------------------------------------------------------------------------


class TestQueuePanelSelection:
    """Tests for queue panel selection behavior."""

    @pytest.mark.gui
    def test_selection_tracks_selected_job_id(self, tk_root, mock_controller, mock_app_state) -> None:
        """Selecting a row should track the selected job ID."""
        panel = QueuePanelV2(tk_root, controller=mock_controller, app_state=mock_app_state)
        jobs = create_test_jobs(3)
        panel.update_jobs(jobs)

        # Simulate selecting the second row
        panel.job_listbox.selection_set(1)
        panel._on_selection_changed(None)

        selected = panel._get_selected_job()
        assert selected is not None
        assert selected.job_id == "test_job_1"

    @pytest.mark.gui
    def test_selection_returns_none_when_empty(self, tk_root, mock_controller, mock_app_state) -> None:
        """Selection should return None when nothing is selected."""
        panel = QueuePanelV2(tk_root, controller=mock_controller, app_state=mock_app_state)
        panel.update_jobs([])

        selected = panel._get_selected_job()
        assert selected is None


# -----------------------------------------------------------------------------
# Queue Panel Button Callback Tests
# -----------------------------------------------------------------------------


class TestQueuePanelButtonCallbacks:
    """Tests for button callback behavior."""

    @pytest.mark.gui
    def test_move_up_calls_callback_with_correct_id(
        self, tk_root, mock_controller, mock_app_state
    ) -> None:
        """Move Up button should call controller with selected job ID."""
        panel = QueuePanelV2(tk_root, controller=mock_controller, app_state=mock_app_state)
        jobs = create_test_jobs(3)
        panel.update_jobs(jobs)

        # Select the second job and click move up
        panel.job_listbox.selection_set(1)
        panel._on_selection_changed(None)
        panel._on_move_up()

        mock_controller.on_queue_move_up_v2.assert_called_once_with("test_job_1")

    @pytest.mark.gui
    def test_move_down_calls_callback_with_correct_id(
        self, tk_root, mock_controller, mock_app_state
    ) -> None:
        """Move Down button should call controller with selected job ID."""
        panel = QueuePanelV2(tk_root, controller=mock_controller, app_state=mock_app_state)
        jobs = create_test_jobs(3)
        panel.update_jobs(jobs)

        # Select the first job and click move down
        panel.job_listbox.selection_set(0)
        panel._on_selection_changed(None)
        panel._on_move_down()

        mock_controller.on_queue_move_down_v2.assert_called_once_with("test_job_0")

    @pytest.mark.gui
    def test_remove_calls_callback_with_correct_id(
        self, tk_root, mock_controller, mock_app_state
    ) -> None:
        """Remove button should call controller with selected job ID."""
        panel = QueuePanelV2(tk_root, controller=mock_controller, app_state=mock_app_state)
        jobs = create_test_jobs(3)
        panel.update_jobs(jobs)

        # Select the second job and click remove
        panel.job_listbox.selection_set(1)
        panel._on_selection_changed(None)
        panel._on_remove()

        mock_controller.on_queue_remove_job_v2.assert_called_once_with("test_job_1")

    @pytest.mark.gui
    def test_clear_calls_callback_without_selection(
        self, tk_root, mock_controller, mock_app_state
    ) -> None:
        """Clear Queue button should work even without selection."""
        panel = QueuePanelV2(tk_root, controller=mock_controller, app_state=mock_app_state)
        jobs = create_test_jobs(3)
        panel.update_jobs(jobs)

        # No selection, just click clear
        panel._on_clear()

        mock_controller.on_queue_clear_v2.assert_called_once()


# -----------------------------------------------------------------------------
# Queue Panel Order Number Tests
# -----------------------------------------------------------------------------


class TestQueuePanelOrderNumbers:
    """Tests for order number display (PR-GUI-F2)."""

    @pytest.mark.gui
    def test_queue_items_have_order_numbers(
        self, tk_root, mock_controller, mock_app_state
    ) -> None:
        """Queue list items should show 1-based order numbers."""
        panel = QueuePanelV2(tk_root, controller=mock_controller, app_state=mock_app_state)
        jobs = create_test_jobs(3)
        panel.update_jobs(jobs)

        # Check that items start with order numbers
        item0 = panel.job_listbox.get(0)
        item1 = panel.job_listbox.get(1)
        item2 = panel.job_listbox.get(2)

        assert item0.startswith("#1")
        assert item1.startswith("#2")
        assert item2.startswith("#3")


# -----------------------------------------------------------------------------
# Running Job Highlighting Tests
# -----------------------------------------------------------------------------


class TestQueuePanelRunningJobHighlight:
    """Tests for running job highlighting (PR-GUI-F2)."""

    @pytest.mark.gui
    def test_running_job_has_indicator(
        self, tk_root, mock_controller, mock_app_state
    ) -> None:
        """Running job in queue should have a visual indicator."""
        panel = QueuePanelV2(tk_root, controller=mock_controller, app_state=mock_app_state)
        jobs = create_test_jobs(3)
        panel.update_jobs(jobs)

        # Set the second job as running
        panel.set_running_job(jobs[1])

        # Check that the second item has the running indicator
        item1 = panel.job_listbox.get(1)
        assert "▶" in item1

    @pytest.mark.gui
    def test_non_running_jobs_no_indicator(
        self, tk_root, mock_controller, mock_app_state
    ) -> None:
        """Non-running jobs should not have the running indicator."""
        panel = QueuePanelV2(tk_root, controller=mock_controller, app_state=mock_app_state)
        jobs = create_test_jobs(3)
        panel.update_jobs(jobs)

        # Set the second job as running
        panel.set_running_job(jobs[1])

        # First and third items should not have the indicator
        item0 = panel.job_listbox.get(0)
        item2 = panel.job_listbox.get(2)
        assert "▶" not in item0
        assert "▶" not in item2

    @pytest.mark.gui
    def test_get_running_job_queue_position(
        self, tk_root, mock_controller, mock_app_state
    ) -> None:
        """get_running_job_queue_position should return 1-based position."""
        panel = QueuePanelV2(tk_root, controller=mock_controller, app_state=mock_app_state)
        jobs = create_test_jobs(3)
        panel.update_jobs(jobs)

        # Set the second job as running
        panel.set_running_job(jobs[1])

        position = panel.get_running_job_queue_position()
        assert position == 2  # 1-based

    @pytest.mark.gui
    def test_get_running_job_queue_position_returns_none_if_not_in_queue(
        self, tk_root, mock_controller, mock_app_state
    ) -> None:
        """get_running_job_queue_position returns None if job not in queue."""
        panel = QueuePanelV2(tk_root, controller=mock_controller, app_state=mock_app_state)
        jobs = create_test_jobs(3)
        panel.update_jobs(jobs)

        # Set a different job as running (not in the list)
        other_job = QueueJobV2.create(config_snapshot={})
        other_job.job_id = "other_job"
        panel.set_running_job(other_job)

        position = panel.get_running_job_queue_position()
        assert position is None


# -----------------------------------------------------------------------------
# Running Job Panel Tests
# -----------------------------------------------------------------------------


class TestRunningJobPanelDisplay:
    """Tests for RunningJobPanelV2 display (PR-GUI-F2)."""

    @pytest.mark.gui
    def test_running_job_panel_shows_job_info(
        self, tk_root, mock_controller, mock_app_state
    ) -> None:
        """Running job panel should display job summary."""
        panel = RunningJobPanelV2(
            tk_root, controller=mock_controller, app_state=mock_app_state
        )
        job = QueueJobV2.create(
            config_snapshot={"prompt": "test prompt", "model": "test_model", "seed": 12345}
        )
        job.status = JobStatusV2.RUNNING

        panel.update_job(job)

        # Job info should be shown
        label_text = panel.job_info_label.cget("text")
        assert label_text != "No job running"

    @pytest.mark.gui
    def test_running_job_panel_shows_queue_origin(
        self, tk_root, mock_controller, mock_app_state
    ) -> None:
        """Running job panel should show queue origin (PR-GUI-F2)."""
        panel = RunningJobPanelV2(
            tk_root, controller=mock_controller, app_state=mock_app_state
        )
        job = QueueJobV2.create(config_snapshot={"prompt": "test"})
        job.status = JobStatusV2.RUNNING

        # Update with queue origin
        panel.update_job(job, queue_origin=3)

        origin_text = panel.queue_origin_label.cget("text")
        assert "(from #3)" in origin_text

    @pytest.mark.gui
    def test_running_job_panel_hides_queue_origin_when_none(
        self, tk_root, mock_controller, mock_app_state
    ) -> None:
        """Queue origin label should be empty when origin is None."""
        panel = RunningJobPanelV2(
            tk_root, controller=mock_controller, app_state=mock_app_state
        )
        job = QueueJobV2.create(config_snapshot={"prompt": "test"})
        job.status = JobStatusV2.RUNNING

        # Update without queue origin
        panel.update_job(job, queue_origin=None)

        origin_text = panel.queue_origin_label.cget("text")
        assert origin_text == ""

    @pytest.mark.gui
    def test_running_job_panel_clears_when_job_none(
        self, tk_root, mock_controller, mock_app_state
    ) -> None:
        """Panel should show 'No job running' when job is None."""
        panel = RunningJobPanelV2(
            tk_root, controller=mock_controller, app_state=mock_app_state
        )

        panel.update_job(None)

        label_text = panel.job_info_label.cget("text")
        assert label_text == "No job running"
        origin_text = panel.queue_origin_label.cget("text")
        assert origin_text == ""


__all__ = [
    "TestQueuePanelSelection",
    "TestQueuePanelButtonCallbacks",
    "TestQueuePanelOrderNumbers",
    "TestQueuePanelRunningJobHighlight",
    "TestRunningJobPanelDisplay",
]
