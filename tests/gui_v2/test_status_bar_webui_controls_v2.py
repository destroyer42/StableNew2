from __future__ import annotations

import tkinter as tk
import pytest

from src.gui.status_bar_v2 import StatusBarV2


class DummyController:
    def __init__(self):
        self.launch_calls = 0
        self.retry_calls = 0

    def on_launch_webui_clicked(self):
        self.launch_calls += 1

    def on_retry_webui_clicked(self):
        self.retry_calls += 1


def _build_status_bar(controller):
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tkinter not available: {exc}")
    root.withdraw()
    status = StatusBarV2(root, controller=controller)
    return root, status


def test_status_bar_buttons_trigger_controller():
    controller = DummyController()
    root, status = _build_status_bar(controller)
    try:
        status._launch_button.invoke()
        status._retry_button.invoke()
        assert controller.launch_calls == 1
        assert controller.retry_calls == 1
    finally:
        root.destroy()


def test_status_bar_webui_state_button_states():
    controller = DummyController()
    root, status = _build_status_bar(controller)
    try:
        status.update_webui_state("connected")
        assert "disabled" in status._launch_button.state()
        status.update_webui_state("error")
        assert "disabled" not in status._launch_button.state()
    finally:
        root.destroy()
