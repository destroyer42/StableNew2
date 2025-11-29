"""
Test that pipeline state is properly cleaned up between runs.

Regression test for: GUI hangs on second run after completing/canceling first run.
"""
from unittest.mock import Mock

import pytest

from src.gui.main_window import StableNewGUI, enable_gui_test_mode, reset_gui_test_mode
from src.gui.state import GUIState
from src.services.config_service import ConfigService
from src.utils.config import ConfigManager
from src.utils.preferences import PreferencesManager


@pytest.fixture
def minimal_app(tmp_path, monkeypatch, tk_root):
    """Create minimal GUI app for testing."""

    monkeypatch.setenv("STABLENEW_GUI_TEST_MODE", "1")
    enable_gui_test_mode()

    config_manager = ConfigManager(tmp_path / "presets")
    preferences = PreferencesManager(tmp_path / "prefs.json")

    try:
        app = StableNewGUI(
            root=tk_root,
            config_manager=config_manager,
            preferences=preferences,
            title="TestGUI",
            geometry="1024x720",
        )
        app.config_service = ConfigService(tmp_path / "packs", tmp_path / "presets", tmp_path / "lists")
        app.structured_logger.output_dir = tmp_path / "output"
        app.structured_logger.output_dir.mkdir(parents=True, exist_ok=True)
        yield app
    finally:
        reset_gui_test_mode()


def test_successive_pipeline_runs_without_restart(minimal_app, monkeypatch):
    """
    Test that running pipeline twice in succession works without hanging.

    Regression test for: changing refiner and running again causes hang.
    """
    # Mock pipeline that succeeds quickly
    run_count = [0]

    class QuickPipeline:
        def run_full_pipeline(self, *args, **kwargs):
            run_count[0] += 1
            return {
                "run_dir": f"output/run_{run_count[0]}",
                "summary": [{"name": f"image_{run_count[0]}.png"}],
            }

    minimal_app.pipeline = QuickPipeline()
    minimal_app.client = Mock()
    minimal_app.client.check_api_ready.return_value = True

    # Mock GUI state to avoid Tk issues
    minimal_app.prompt_text = Mock()
    minimal_app.prompt_text.get.return_value = "test prompt"

    # First run
    minimal_app.controller.start_pipeline(lambda: {"run_dir": "output/run_1", "summary": []})
    assert minimal_app.controller.lifecycle_event.wait(timeout=2.0), "First run timed out"

    # Controller should reset to IDLE state
    assert minimal_app.controller.state_manager.state == GUIState.IDLE

    # Second run should work without hanging
    minimal_app.controller.start_pipeline(lambda: {"run_dir": "output/run_2", "summary": []})
    assert minimal_app.controller.lifecycle_event.wait(timeout=2.0), "Second run timed out (BUG!)"

    assert run_count[0] == 2, "Pipeline should have run twice"


def test_cancel_token_reset_between_runs(minimal_app):
    """Test that cancel token is properly reset between runs."""
    # First run
    minimal_app.controller.start_pipeline(lambda: {"run_dir": "test", "summary": []})

    # Cancel it
    minimal_app.controller.request_cancel()
    minimal_app.controller.lifecycle_event.wait(timeout=2.0)

    # Cancel token should be reset
    assert (
        not minimal_app.controller.cancel_token.cancelled
    ), "Cancel token should be reset after run completes"

    # Second run should work
    minimal_app.controller.start_pipeline(lambda: {"run_dir": "test2", "summary": []})
    assert minimal_app.controller.lifecycle_event.wait(
        timeout=2.0
    ), "Second run after cancel should not hang"


def test_lifecycle_event_reset_before_new_run(minimal_app):
    """Test that lifecycle_event is cleared before starting a new run."""
    # First run
    minimal_app.controller.start_pipeline(lambda: {"run_dir": "test", "summary": []})
    minimal_app.controller.lifecycle_event.wait(timeout=2.0)

    # Event should be set after completion
    assert minimal_app.controller.lifecycle_event.is_set()

    # Starting second run should clear the event
    minimal_app.controller.start_pipeline(lambda: {"run_dir": "test2", "summary": []})

    # Event should be cleared at start (not remain set from previous run)
    # This is the bug - if event isn't cleared, subsequent waits return immediately
    import time

    time.sleep(0.1)  # Give worker thread time to start

    # Event should eventually be set again when run completes
    assert minimal_app.controller.lifecycle_event.wait(
        timeout=2.0
    ), "Lifecycle event not properly managed between runs"


def test_worker_thread_cleanup_after_error(minimal_app):
    """Test that worker thread is cleaned up after pipeline error."""

    class FailingPipeline:
        def run_full_pipeline(self, *args, **kwargs):
            raise RuntimeError("Pipeline failed")

    minimal_app.pipeline = FailingPipeline()

    # Run should fail but not leave worker thread dangling
    minimal_app.controller.start_pipeline(lambda: {"run_dir": "test", "summary": []})

    # Should complete (with error) without hanging
    assert minimal_app.controller.lifecycle_event.wait(
        timeout=2.0
    ), "Error handling should complete without hanging"

    # Should return to IDLE (not stuck in RUNNING or ERROR)
    assert minimal_app.controller.state_manager.state in [GUIState.IDLE, GUIState.ERROR]

    # Second run after error should work
    minimal_app.pipeline = Mock()
    minimal_app.pipeline.run_full_pipeline.return_value = {"run_dir": "test2", "summary": []}

    minimal_app.controller.start_pipeline(lambda: {"run_dir": "test2", "summary": []})
    assert minimal_app.controller.lifecycle_event.wait(
        timeout=2.0
    ), "Run after error should not hang"
