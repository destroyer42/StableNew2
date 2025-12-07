"""Tests for PR-111: Run Controls UX + Status Feedback.

Validates:
- AppStateV2 new run state fields
- PipelineRunControlsV2.refresh_states() button enable/disable logic
"""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass

import pytest

from src.gui.app_state_v2 import AppStateV2
from src.gui.panels_v2.pipeline_run_controls_v2 import PipelineRunControlsV2


# ---------------------------------------------------------------------------
# AppStateV2 Run State Field Tests
# ---------------------------------------------------------------------------


class TestAppStateV2RunStateFields:
    """Tests for new run state fields in AppStateV2."""

    def test_is_run_in_progress_default_false(self) -> None:
        state = AppStateV2()
        assert state.is_run_in_progress is False

    def test_is_direct_run_in_progress_default_false(self) -> None:
        state = AppStateV2()
        assert state.is_direct_run_in_progress is False

    def test_is_queue_paused_default_false(self) -> None:
        state = AppStateV2()
        assert state.is_queue_paused is False

    def test_last_run_job_id_default_none(self) -> None:
        state = AppStateV2()
        assert state.last_run_job_id is None

    def test_last_error_message_default_none(self) -> None:
        state = AppStateV2()
        assert state.last_error_message is None

    def test_set_is_run_in_progress_true(self) -> None:
        state = AppStateV2()
        state.set_is_run_in_progress(True)
        assert state.is_run_in_progress is True

    def test_set_is_direct_run_in_progress_true(self) -> None:
        state = AppStateV2()
        state.set_is_direct_run_in_progress(True)
        assert state.is_direct_run_in_progress is True

    def test_set_is_queue_paused_true(self) -> None:
        state = AppStateV2()
        state.set_is_queue_paused(True)
        assert state.is_queue_paused is True

    def test_set_last_run_job_id(self) -> None:
        state = AppStateV2()
        state.set_last_run_job_id("job_123")
        assert state.last_run_job_id == "job_123"

    def test_set_last_error_message(self) -> None:
        state = AppStateV2()
        state.set_last_error_message("Pipeline failed")
        assert state.last_error_message == "Pipeline failed"

    def test_set_is_run_in_progress_notifies_listener(self) -> None:
        state = AppStateV2()
        notifications = []
        state.subscribe("is_run_in_progress", lambda: notifications.append("notified"))
        state.set_is_run_in_progress(True)
        assert notifications == ["notified"]

    def test_set_is_direct_run_in_progress_notifies_listener(self) -> None:
        state = AppStateV2()
        notifications = []
        state.subscribe("is_direct_run_in_progress", lambda: notifications.append("notified"))
        state.set_is_direct_run_in_progress(True)
        assert notifications == ["notified"]

    def test_set_is_queue_paused_notifies_listener(self) -> None:
        state = AppStateV2()
        notifications = []
        state.subscribe("is_queue_paused", lambda: notifications.append("notified"))
        state.set_is_queue_paused(True)
        assert notifications == ["notified"]

    def test_set_last_run_job_id_notifies_listener(self) -> None:
        state = AppStateV2()
        notifications = []
        state.subscribe("last_run_job_id", lambda: notifications.append("notified"))
        state.set_last_run_job_id("job_456")
        assert notifications == ["notified"]

    def test_set_last_error_message_notifies_listener(self) -> None:
        state = AppStateV2()
        notifications = []
        state.subscribe("last_error_message", lambda: notifications.append("notified"))
        state.set_last_error_message("Error occurred")
        assert notifications == ["notified"]

    def test_no_notify_if_same_value(self) -> None:
        state = AppStateV2()
        state.set_is_run_in_progress(False)  # Set to same default
        notifications = []
        state.subscribe("is_run_in_progress", lambda: notifications.append("notified"))
        state.set_is_run_in_progress(False)  # No change
        assert notifications == []


# ---------------------------------------------------------------------------
# PR-203: Auto-run queue flag tests
# ---------------------------------------------------------------------------


class TestAppStateV2AutoRunQueue:
    """Tests for PR-203 auto_run_queue field."""

    def test_auto_run_queue_default_false(self) -> None:
        state = AppStateV2()
        assert state.auto_run_queue is False

    def test_set_auto_run_queue_true(self) -> None:
        state = AppStateV2()
        state.set_auto_run_queue(True)
        assert state.auto_run_queue is True

    def test_set_auto_run_queue_notifies_listener(self) -> None:
        state = AppStateV2()
        notifications = []
        state.subscribe("auto_run_queue", lambda: notifications.append("notified"))
        state.set_auto_run_queue(True)
        assert notifications == ["notified"]


# ---------------------------------------------------------------------------
# PipelineRunControlsV2.refresh_states() Button State Tests
# PR-203: Updated for simplified controls (no run_button, run_now_button, stop_button)
# ---------------------------------------------------------------------------


@dataclass
class MockAppState:
    """Minimal mock of AppStateV2 for testing button states."""

    is_run_in_progress: bool = False
    is_direct_run_in_progress: bool = False
    is_queue_paused: bool = False
    current_pack: str | None = None
    auto_run_queue: bool = False
    running_job: dict | None = None
    queue_items: list = None

    def __post_init__(self):
        if self.queue_items is None:
            self.queue_items = []


@pytest.mark.gui
@pytest.mark.skip(reason="PR-GUI-F1: PipelineRunControlsV2 buttons removed, controls moved to QueuePanelV2")
class TestPipelineRunControlsRefreshStates:
    """Tests for refresh_states() button enable/disable logic (PR-203 simplified version)."""

    def test_add_button_enabled_with_pack(self, tk_root: tk.Tk) -> None:
        """PR-203: Add to Queue button enabled when pack is selected."""
        app_state = MockAppState(current_pack="test_pack")
        controls = PipelineRunControlsV2(tk_root, app_state=app_state)

        controls.refresh_states()

        assert "disabled" not in controls.add_button.state()

    def test_add_button_disabled_without_pack(self, tk_root: tk.Tk) -> None:
        """PR-203: Add to Queue button disabled when no pack is selected."""
        app_state = MockAppState(current_pack=None)
        controls = PipelineRunControlsV2(tk_root, app_state=app_state)

        controls.refresh_states()

        assert "disabled" in controls.add_button.state()

    def test_clear_draft_always_enabled(self, tk_root: tk.Tk) -> None:
        """Clear Draft button always enabled regardless of state."""
        app_state = MockAppState(
            is_run_in_progress=True,
            is_queue_paused=True,
            current_pack=None,
        )
        controls = PipelineRunControlsV2(tk_root, app_state=app_state)

        controls.refresh_states()

        assert "disabled" not in controls.clear_draft_button.state()

    def test_refresh_states_handles_none_app_state(self, tk_root: tk.Tk) -> None:
        """refresh_states() handles None app_state gracefully."""
        controls = PipelineRunControlsV2(tk_root, app_state=None)

        # Should not raise
        controls.refresh_states()

    def test_refresh_states_handles_missing_attributes(self, tk_root: tk.Tk) -> None:
        """refresh_states() handles app_state with missing attributes."""
        minimal_state = object()
        controls = PipelineRunControlsV2(tk_root, app_state=minimal_state)

        # Should not raise, uses getattr defaults
        controls.refresh_states()

    def test_pause_resume_button_shows_pause_when_not_paused(self, tk_root: tk.Tk) -> None:
        """PR-203: Pause/Resume button shows 'Pause Queue' when not paused."""
        app_state = MockAppState(is_queue_paused=False)
        controls = PipelineRunControlsV2(tk_root, app_state=app_state)

        controls.refresh_states()

        button_text = controls.pause_resume_button.cget("text")
        assert "Pause" in button_text

    def test_pause_resume_button_shows_resume_when_paused(self, tk_root: tk.Tk) -> None:
        """PR-203: Pause/Resume button shows 'Resume Queue' when paused."""
        app_state = MockAppState(is_queue_paused=True)
        controls = PipelineRunControlsV2(tk_root, app_state=app_state)

        controls.refresh_states()

        button_text = controls.pause_resume_button.cget("text")
        assert "Resume" in button_text

    def test_status_shows_idle_when_empty(self, tk_root: tk.Tk) -> None:
        """PR-203: Status label shows 'Idle' when queue is empty."""
        app_state = MockAppState(queue_items=[])
        controls = PipelineRunControlsV2(tk_root, app_state=app_state)

        controls.refresh_states()

        status_text = controls.status_label.cget("text")
        assert "Idle" in status_text

    def test_status_shows_pending_count(self, tk_root: tk.Tk) -> None:
        """PR-203: Status label shows pending job count."""
        app_state = MockAppState(queue_items=["job1", "job2", "job3"])
        controls = PipelineRunControlsV2(tk_root, app_state=app_state)

        controls.refresh_states()

        status_text = controls.status_label.cget("text")
        assert "3" in status_text

    def test_status_shows_running_when_job_active(self, tk_root: tk.Tk) -> None:
        """PR-203: Status label shows 'Running' when a job is active."""
        app_state = MockAppState(running_job={"job_id": "test123"})
        controls = PipelineRunControlsV2(tk_root, app_state=app_state)

        controls.refresh_states()

        status_text = controls.status_label.cget("text")
        assert "Running" in status_text

