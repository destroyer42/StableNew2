"""Tests for PR-111: Run Controls UX + Status Feedback.

Validates:
- AppStateV2 queue-first run state fields
"""

from __future__ import annotations

from src.gui.app_state_v2 import AppStateV2

# ---------------------------------------------------------------------------
# AppStateV2 Run State Field Tests
# ---------------------------------------------------------------------------


class TestAppStateV2RunStateFields:
    """Tests for new run state fields in AppStateV2."""

    def test_is_run_in_progress_default_false(self) -> None:
        state = AppStateV2()
        assert state.is_run_in_progress is False

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

    def test_set_run_config_updates_canonical_config_layers(self) -> None:
        state = AppStateV2()

        state.set_run_config(
            {
                "run_mode": "queue",
                "source": "run",
                "prompt_source": "pack",
                "video_workflow": {
                    "workflow_id": "ltx_multiframe_anchor_v1",
                    "backend_id": "comfy",
                },
            }
        )

        assert state.intent_config["run_mode"] == "queue"
        assert state.intent_config["source"] == "run"
        assert state.execution_config["video_workflow"]["workflow_id"] == "ltx_multiframe_anchor_v1"
        assert state.backend_options["video"]["workflow"]["backend_id"] == "comfy"

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

    def test_auto_run_queue_default_true(self) -> None:
        state = AppStateV2()
        assert state.auto_run_queue is True

    def test_set_auto_run_queue_true(self) -> None:
        state = AppStateV2()
        state.set_auto_run_queue(True)
        assert state.auto_run_queue is True

    def test_set_auto_run_queue_notifies_listener(self) -> None:
        state = AppStateV2()
        notifications = []
        state.subscribe("auto_run_queue", lambda: notifications.append("notified"))
        state.set_auto_run_queue(False)
        assert notifications == ["notified"]
