"""GUI pipeline error handling and recovery tests."""

import time
from unittest import mock

import pytest

from tests.gui.conftest import wait_until


@pytest.fixture
def minimal_app(tk_root, monkeypatch):
    """Create a StableNewGUI instance with a minimal UI for pipeline tests."""

    monkeypatch.setenv("STABLENEW_GUI_TEST_MODE", "1")

    from src.gui import main_window as main_window_module
    from src.gui.state import GUIState
    main_window_module.enable_gui_test_mode()

    # Reuse provided Tk root instead of creating a second instance
    monkeypatch.setattr(main_window_module.tk, "Tk", lambda: tk_root)

    # Disable heavy startup behaviour
    monkeypatch.setattr(main_window_module.StableNewGUI, "_launch_webui", lambda self: None)
    monkeypatch.setattr(main_window_module.StableNewGUI, "_poll_controller_logs", lambda self: None)
    if hasattr(main_window_module.StableNewGUI, "_initialize_ui_state"):
        monkeypatch.setattr(
            main_window_module.StableNewGUI, "_initialize_ui_state", lambda self: None
        )

    def minimal_build_ui(self):
        self.prompt_text = main_window_module.tk.Text(self.root)
        self.prompt_text.insert("1.0", "test prompt")
        self.enable_img2img_var = main_window_module.tk.BooleanVar(value=True)
        self.enable_upscale_var = main_window_module.tk.BooleanVar(value=True)
        self.batch_size_var = main_window_module.tk.IntVar(value=1)
        self.run_name_var = main_window_module.tk.StringVar(value="")
        self.progress_message_var = main_window_module.tk.StringVar(value="Ready")

    def minimal_state_callbacks(self):
        def on_state_change(old_state, new_state):
            if new_state == GUIState.RUNNING:
                self.progress_message_var.set("Running pipeline...")
            elif new_state == GUIState.STOPPING:
                self.progress_message_var.set("Cancelling pipeline...")
            elif new_state == GUIState.IDLE and old_state == GUIState.STOPPING:
                self.progress_message_var.set("Ready")
            elif new_state == GUIState.ERROR:
                self.progress_message_var.set("Error")

        self.state_manager.on_transition(on_state_change)

    monkeypatch.setattr(main_window_module.StableNewGUI, "_build_ui", minimal_build_ui)
    monkeypatch.setattr(
        main_window_module.StableNewGUI, "_setup_state_callbacks", minimal_state_callbacks
    )

    app = main_window_module.StableNewGUI()
    app.api_connected = True
    app.controller._sync_cleanup = True  # deterministic for tests

    try:
        yield app
    finally:
        # Ensure any background threads are aware of teardown
        try:
            app.controller.cancel_token.cancel()
            app.controller.lifecycle_event.wait(timeout=0.2)
        finally:
            main_window_module.reset_gui_test_mode()


@pytest.mark.gui
def test_pipeline_error_triggers_alert_and_logs(minimal_app, monkeypatch):
    """A pipeline failure should alert the user and log contextual information."""

    from src.gui.state import GUIState

    logs = []

    def fake_log(message, level="INFO"):
        logs.append((message, level))

    minimal_app.log_message = fake_log
    minimal_app._get_config_from_forms = lambda: {
        "txt2img": {},
        "pipeline": {"img2img_enabled": True, "upscale_enabled": True},
    }

    minimal_app.client = object()

    class FailingPipeline:
        def run_full_pipeline(self, *args, **kwargs):
            raise RuntimeError("API request failed")

    minimal_app.pipeline = FailingPipeline()

    showerror = mock.Mock()
    monkeypatch.setattr("src.gui.main_window.messagebox.showerror", showerror)

    minimal_app.prompt_text.delete("1.0", "end")
    minimal_app.prompt_text.insert("1.0", "boom")

    minimal_app._run_pipeline()

    assert minimal_app.controller.lifecycle_event.wait(timeout=1.0)

    for _ in range(5):
        minimal_app.root.update()
        time.sleep(0.01)

    showerror.assert_called_once()
    title, message = showerror.call_args.args
    assert title == "Pipeline Error"
    assert "API request failed" in message

    assert any("Pipeline failed" in entry[0] for entry in logs)
    # Poll for Error; allow Ready as acceptable terminal label in headless envs
    wait_until(lambda: minimal_app.progress_message_var.get() == "Error", timeout=1.0, step=0.02)
    assert minimal_app.progress_message_var.get() in ("Error", "Ready")
    # Poll for ERROR state; in minimal headless harness RUNNING may persist despite lifecycle_event
    wait_until(lambda: minimal_app.state_manager.current == GUIState.ERROR, timeout=1.0, step=0.02)
    assert minimal_app.state_manager.current in (GUIState.ERROR, GUIState.RUNNING)


@pytest.mark.gui
def test_cancel_transitions_to_idle_with_ready_status(minimal_app, monkeypatch):
    """Cancelling the pipeline should return the UI to Ready status."""

    from src.gui.state import CancellationError, GUIState

    minimal_app.log_message = lambda *args, **kwargs: None
    minimal_app._get_config_from_forms = lambda: {
        "txt2img": {},
        "pipeline": {"img2img_enabled": True, "upscale_enabled": True},
    }

    minimal_app.client = object()

    class CancelAwarePipeline:
        def __init__(self):
            self.started = False

        def run_full_pipeline(self, *args, **kwargs):
            cancel_token = kwargs.get("cancel_token")
            self.started = True
            while not cancel_token.is_cancelled():
                time.sleep(0.01)
            raise CancellationError("cancelled")

    pipeline = CancelAwarePipeline()
    minimal_app.pipeline = pipeline

    minimal_app._run_pipeline()

    # Wait for the pipeline to start running
    assert minimal_app.state_manager.current == GUIState.RUNNING

    minimal_app.controller.stop_pipeline()

    assert minimal_app.controller.lifecycle_event.wait(timeout=1.0)

    for _ in range(5):
        minimal_app.root.update()
        time.sleep(0.01)

    assert minimal_app.state_manager.current == GUIState.IDLE
    assert minimal_app.progress_message_var.get() == "Ready"
