"""Tests for pipeline controller."""

import time

import pytest

from src.gui.controller import LogMessage, PipelineController
from src.gui.state import GUIState, StateManager


class TestLogMessage:
    """Tests for LogMessage."""

    def test_creation(self):
        """Test log message creation."""
        msg = LogMessage("test message", "INFO")
        assert msg.message == "test message"
        assert msg.level == "INFO"
        assert msg.timestamp > 0

    def test_default_level(self):
        """Test default log level."""
        msg = LogMessage("test")
        assert msg.level == "INFO"


class TestPipelineController:
    """Tests for PipelineController."""

    @pytest.fixture
    def controller(self):
        """Create controller instance with synchronous cleanup for tests."""
        state_manager = StateManager()
        controller = PipelineController(state_manager)
        controller._sync_cleanup = (
            True  # TEST HOOK: force synchronous cleanup for deterministic tests
        )
        return controller

    def test_initial_state(self, controller):
        """Test initial controller state."""
        assert not controller.is_running()
        assert not controller.is_stopping()
        assert controller.state_manager.current == GUIState.IDLE

    def wait_until(self, predicate, timeout=5.0, interval=0.01):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(interval)
        return False

    def test_start_pipeline_success(self, controller):
        """Test successful pipeline start."""
        completed = []

        def pipeline_func():
            time.sleep(0.05)  # Small delay to ensure we can check running state
            return {"status": "success"}

        def on_complete(result):
            completed.append(result)

        started = controller.start_pipeline(pipeline_func, on_complete=on_complete)
        assert started

        # Give thread a moment to actually start
        time.sleep(0.01)
        assert controller.is_running()

        # Wait for completion (poll state)
        ok = self.wait_until(lambda: controller.is_terminal, timeout=2.0)
        assert ok, "Controller did not reach terminal state in time"

        assert len(completed) == 1
        assert completed[0]["status"] == "success"
        assert controller.state_manager.current == GUIState.IDLE

    def test_start_pipeline_already_running(self, controller):
        """Test cannot start pipeline when already running."""

        def long_pipeline():
            time.sleep(0.5)
            return {}

        controller.start_pipeline(long_pipeline)
        assert controller.is_running()

        # Try to start again
        started = controller.start_pipeline(long_pipeline)
        assert not started

        # Cleanup
        controller.stop_pipeline()
        ok = self.wait_until(lambda: controller.is_terminal, timeout=2.0)
        assert ok, "Controller did not reach terminal state in time"

    def test_pipeline_error_handling(self, controller):
        """Test pipeline error handling."""
        errors = []

        def failing_pipeline():
            raise ValueError("Test error")

        def on_error(e):
            errors.append(e)

        controller.start_pipeline(failing_pipeline, on_error=on_error)
        time.sleep(0.1)
        ok = self.wait_until(lambda: controller.is_terminal, timeout=2.0)
        assert ok, "Controller did not reach terminal state in time"

        assert len(errors) == 1
        assert isinstance(errors[0], ValueError)
        assert controller.state_manager.current == GUIState.ERROR

    def test_pipeline_cancellation(self, controller):
        """Test pipeline cancellation."""
        started = []
        completed = []

        def cancellable_pipeline():
            started.append(True)
            for i in range(100):
                controller.cancel_token.check_cancelled()
                time.sleep(0.01)
            completed.append(True)
            return {}

        controller.start_pipeline(cancellable_pipeline)
        time.sleep(0.05)  # Let it start

        assert len(started) == 1
        assert len(completed) == 0

        # Stop the pipeline
        stopped = controller.stop_pipeline()
        assert stopped
        assert controller.is_stopping() or controller.state_manager.current == GUIState.IDLE

        # Wait for cleanup
        ok = self.wait_until(lambda: controller.is_terminal, timeout=2.0)
        assert ok, "Controller did not reach terminal state in time"

        # Should not have completed
        assert len(completed) == 0

    def test_stop_when_not_running(self, controller):
        """Test stop does nothing when not running."""
        stopped = controller.stop_pipeline()
        assert not stopped

    def test_log_messages(self, controller):
        """Test log message queuing."""
        controller._log("Test message 1", "INFO")
        controller._log("Test message 2", "WARNING")

        messages = controller.get_log_messages()
        assert len(messages) == 2
        assert messages[0].message == "Test message 1"
        assert messages[0].level == "INFO"
        assert messages[1].message == "Test message 2"
        assert messages[1].level == "WARNING"

        # Queue should be empty now
        messages = controller.get_log_messages()
        assert len(messages) == 0

    def test_cancel_token_reset(self, controller):
        """Test cancel token is reset on new run."""

        def quick_pipeline():
            return {}

        # First run
        controller.start_pipeline(quick_pipeline)
        time.sleep(0.1)
        ok = self.wait_until(lambda: controller.is_terminal, timeout=2.0)
        assert ok, "Controller did not reach terminal state in time (first run)"

        # Cancel
        controller.cancel_token.cancel()
        assert controller.cancel_token.is_cancelled()

        # Start new run - token should be reset
        controller.state_manager.reset()
        controller.start_pipeline(quick_pipeline)
        assert not controller.cancel_token.is_cancelled()

        # Cleanup
        ok = self.wait_until(lambda: controller.is_terminal, timeout=2.0)
        assert ok, "Controller did not reach terminal state in time (second run)"

    def test_progress_callbacks(self, controller):
        """Progress callbacks should be invoked in order."""

        calls = []

        controller.set_status_callback(lambda stage: calls.append(("stage", stage)))
        controller.set_progress_callback(lambda percent: calls.append(("percent", percent)))
        controller.set_eta_callback(lambda eta: calls.append(("eta", eta)))

        controller.report_progress("txt2img", 42.5, "ETA: 00:10")

        assert calls == [
            ("stage", "txt2img"),
            ("percent", 42.5),
            ("eta", "ETA: 00:10"),
        ]

    def test_cancel_emits_final_progress(self, controller):
        """Cancellation should emit a final progress update."""

        reports = []

        controller.set_status_callback(lambda stage: reports.append(("stage", stage)))
        controller.set_progress_callback(lambda percent: reports.append(("percent", percent)))
        controller.set_eta_callback(lambda eta: reports.append(("eta", eta)))

        def cancellable_pipeline():
            controller.report_progress("txt2img", 25.0, "ETA: 00:30")
            for _ in range(20):
                time.sleep(0.01)
                controller.cancel_token.check_cancelled()

        controller.start_pipeline(cancellable_pipeline)
        time.sleep(0.05)

        controller.stop_pipeline()

        ok = self.wait_until(lambda: controller.is_terminal, timeout=2.0)
        assert ok, "Controller did not reach terminal state in time"

        # Final three callbacks correspond to the cancellation update
        assert reports[-3:] == [
            ("stage", "Cancelled"),
            ("percent", 25.0),
            ("eta", "Cancelled"),
        ]

    def test_subprocess_registration(self, controller):
        """Test subprocess registration for cancellation."""
        import subprocess

        # Create dummy subprocess
        proc = subprocess.Popen(
            ["ping", "-n", "10", "127.0.0.1"], stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )

        try:
            controller.register_subprocess(proc)
            assert controller._current_subprocess == proc

            controller.unregister_subprocess()
            assert controller._current_subprocess is None
        finally:
            # Cleanup
            try:
                proc.terminate()
                proc.wait(timeout=1.0)
            except Exception:
                pass
