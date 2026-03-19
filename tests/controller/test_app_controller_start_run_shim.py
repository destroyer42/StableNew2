from __future__ import annotations

import tkinter as tk
from typing import Any

import pytest

from src.controller.app_controller import AppController, LifecycleState
from src.gui.main_window_v2 import MainWindow
from tests.helpers.job_service_di_test_helpers import make_stubbed_job_service


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
    controller = AppController(
        window,
        pipeline_runner=None,
        threaded=False,
        job_service=make_stubbed_job_service(),  # PR-0114C-Ty: DI for tests
    )
    return controller


def test_start_run_delegates_to_queue_backed_start_run_v2(controller, monkeypatch):
    called: list[Any] = []

    def fake_start_run_v2():
        called.append("start_run_v2")
        return {"status": "ok"}

    monkeypatch.setattr(controller, "start_run_v2", fake_start_run_v2)

    result = controller.start_run()

    assert called == ["start_run_v2"]
    assert result == {"status": "ok"}
    assert controller.state.lifecycle == LifecycleState.IDLE


def test_start_run_refuses_when_already_running(controller, monkeypatch):
    controller.state.lifecycle = LifecycleState.RUNNING
    called = []
    monkeypatch.setattr(controller, "start_run_v2", lambda: called.append("start_run_v2"))

    result = controller.start_run()

    assert result is None
    assert called == []
