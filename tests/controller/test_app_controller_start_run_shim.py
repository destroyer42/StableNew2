from __future__ import annotations

from typing import Any

import pytest
import tkinter as tk

from src.controller.app_controller import AppController, LifecycleState
from src.gui.main_window_v2 import MainWindow


@pytest.fixture
def tk_root():
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tkinter not available: {exc}")
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def controller(tk_root):
    window = MainWindow(tk_root)
    controller = AppController(window, pipeline_runner=None, threaded=False)
    return controller


def test_start_run_delegates_to_run_pipeline(controller, monkeypatch):
    called: list[Any] = []

    def fake_run_pipeline():
        called.append("run")
        return {"status": "ok"}

    monkeypatch.setattr(controller, "run_pipeline", fake_run_pipeline)

    result = controller.start_run()

    assert called == ["run"]
    assert result == {"status": "ok"}
    assert controller.state.lifecycle == LifecycleState.IDLE


def test_start_run_refuses_when_already_running(controller, monkeypatch):
    controller.state.lifecycle = LifecycleState.RUNNING
    called = []
    monkeypatch.setattr(controller, "run_pipeline", lambda: called.append("run"))

    result = controller.start_run()

    assert result is None
    assert called == []
