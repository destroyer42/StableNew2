import tkinter as tk
import pytest


class _FakeRunner:
    def __init__(self):
        self.called = 0
        self.last_config = None

    def run(self, config, cancel_token, log_fn=None):  # noqa: ARG002
        self.called += 1
        self.last_config = config


def test_run_button_triggers_controller(monkeypatch):
    from src.controller.app_controller import AppController
    from src.gui.main_window_v2 import MainWindow

    try:
        root = tk.Tk()
    except Exception:  # pragma: no cover - Tk unavailable in environment
        pytest.skip("Tkinter not available in test environment")

    root.withdraw()
    try:
        runner = _FakeRunner()
        window = MainWindow(root)
        controller = AppController(window, pipeline_runner=runner, threaded=False)

        window.header_zone.run_button.invoke()

        assert runner.called == 1
        assert controller.state.lifecycle.name == "IDLE"
    finally:
        root.destroy()
