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
# PipelineRunControlsV2.refresh_states() Button State Tests
# ---------------------------------------------------------------------------


@dataclass
class MockAppState:
    """Minimal mock of AppStateV2 for testing button states."""

    is_run_in_progress: bool = False
    is_direct_run_in_progress: bool = False
    is_queue_paused: bool = False
    current_pack: str | None = None


@pytest.mark.gui
class TestPipelineRunControlsRefreshStates:
    """Tests for refresh_states() button enable/disable logic."""

    def test_all_buttons_enabled_when_idle_with_pack(self, tk_root: tk.Tk) -> None:
        """When idle with a pack selected, Run/Run Now/Add to Queue enabled, Stop disabled."""
        app_state = MockAppState(current_pack="test_pack")
        controls = PipelineRunControlsV2(tk_root, app_state=app_state)

        controls.refresh_states()

        assert str(controls.run_button.cget("state")) == "normal"
        assert str(controls.run_now_button.cget("state")) == "normal"
        assert str(controls.add_button.cget("state")) == "normal"
        assert str(controls.stop_button.cget("state")) == "disabled"

    def test_run_now_disabled_during_direct_run(self, tk_root: tk.Tk) -> None:
        """Run Now button disabled when direct run is in progress."""
        app_state = MockAppState(
            is_run_in_progress=True,
            is_direct_run_in_progress=True,
            current_pack="test_pack",
        )
        controls = PipelineRunControlsV2(tk_root, app_state=app_state)

        controls.refresh_states()

        assert str(controls.run_now_button.cget("state")) == "disabled"

    def test_run_disabled_during_direct_run(self, tk_root: tk.Tk) -> None:
        """Run button disabled when direct run is in progress."""
        app_state = MockAppState(
            is_run_in_progress=True,
            is_direct_run_in_progress=True,
            current_pack="test_pack",
        )
        controls = PipelineRunControlsV2(tk_root, app_state=app_state)

        controls.refresh_states()

        assert str(controls.run_button.cget("state")) == "disabled"

    def test_run_disabled_when_queue_paused(self, tk_root: tk.Tk) -> None:
        """Run button disabled when queue is paused."""
        app_state = MockAppState(is_queue_paused=True, current_pack="test_pack")
        controls = PipelineRunControlsV2(tk_root, app_state=app_state)

        controls.refresh_states()

        assert str(controls.run_button.cget("state")) == "disabled"

    def test_add_to_queue_disabled_without_pack(self, tk_root: tk.Tk) -> None:
        """Add to Queue button disabled when no pack is selected."""
        app_state = MockAppState(current_pack=None)
        controls = PipelineRunControlsV2(tk_root, app_state=app_state)

        controls.refresh_states()

        assert str(controls.add_button.cget("state")) == "disabled"

    def test_add_to_queue_disabled_when_queue_paused(self, tk_root: tk.Tk) -> None:
        """Add to Queue button disabled when queue is paused."""
        app_state = MockAppState(is_queue_paused=True, current_pack="test_pack")
        controls = PipelineRunControlsV2(tk_root, app_state=app_state)

        controls.refresh_states()

        assert str(controls.add_button.cget("state")) == "disabled"

    def test_stop_enabled_during_run(self, tk_root: tk.Tk) -> None:
        """Stop button enabled when run is in progress."""
        app_state = MockAppState(is_run_in_progress=True, current_pack="test_pack")
        controls = PipelineRunControlsV2(tk_root, app_state=app_state)

        controls.refresh_states()

        assert str(controls.stop_button.cget("state")) == "normal"

    def test_clear_draft_always_enabled(self, tk_root: tk.Tk) -> None:
        """Clear Draft button always enabled regardless of state."""
        app_state = MockAppState(
            is_run_in_progress=True,
            is_queue_paused=True,
            current_pack=None,
        )
        controls = PipelineRunControlsV2(tk_root, app_state=app_state)

        controls.refresh_states()

        assert str(controls.clear_draft_button.cget("state")) == "normal"

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

    def test_queue_run_allows_run_now(self, tk_root: tk.Tk) -> None:
        """During queue (non-direct) run, Run Now stays enabled."""
        app_state = MockAppState(
            is_run_in_progress=True,
            is_direct_run_in_progress=False,  # Queue run, not direct
            current_pack="test_pack",
        )
        controls = PipelineRunControlsV2(tk_root, app_state=app_state)

        controls.refresh_states()

        assert str(controls.run_now_button.cget("state")) == "normal"
