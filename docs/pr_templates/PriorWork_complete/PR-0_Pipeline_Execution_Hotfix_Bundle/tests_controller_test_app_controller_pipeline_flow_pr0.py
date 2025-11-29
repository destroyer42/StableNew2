"""Tests for PR-0: AppController ↔ PipelineRunner flow.

These tests are intentionally focused and should be created FIRST (TDD).
They assume the presence of:

- src.gui.main_window_v2.MainWindow
- src.controller.app_controller.AppController, LifecycleState
- src.controller.pipeline_runner.PipelineRunner (Protocol-like)
"""

import tkinter as tk
from typing import Callable, Any

import pytest

from src.gui.main_window_v2 import MainWindow
from src.controller.app_controller import AppController, LifecycleState


class FakePipelineRunner:
    """A simple fake implementing the PipelineRunner.run API for tests."""

    def __init__(self, should_raise: bool = False, simulate_long_run: bool = False) -> None:
        self.should_raise = should_raise
        self.simulate_long_run = simulate_long_run
        self.run_calls: list[dict[str, Any]] = []

    def run(self, config, cancel_token, log_fn: Callable[[str], None]) -> None:  # noqa: D401
        """Record the call and optionally raise or simulate work."""
        self.run_calls.append(
            {
                "config": config,
                "cancel_token": cancel_token,
            }
        )
        log_fn("[fake] pipeline started")
        if self.should_raise:
            raise RuntimeError("Fake pipeline error")
        if self.simulate_long_run:
            # Instead of actually sleeping, just check cancel_token once
            if cancel_token.is_cancelled():
                log_fn("[fake] observed cancel, aborting")
                return
        log_fn("[fake] pipeline finished")


@pytest.fixture
def tk_root():
    """Create and destroy a Tk root per test to avoid cross-test interference."""
    root = tk.Tk()
    root.withdraw()
    try:
        yield root
    finally:
        root.destroy()


@pytest.fixture
def controller(tk_root):
    """Provide an AppController with a FakePipelineRunner, in synchronous mode."""
    window = MainWindow(tk_root)
    fake_runner = FakePipelineRunner()
    controller = AppController(window, pipeline_runner=fake_runner, threaded=False)
    # Attach the fake to the controller for easy access in tests
    controller._test_fake_runner = fake_runner  # type: ignore[attr-defined]
    return controller


def _get_log_text(controller: AppController) -> str:
    text_widget = controller.main_window.bottom_zone.log_text
    return text_widget.get("1.0", "end")


def test_run_starts_pipeline_and_returns_to_idle(controller: AppController):
    assert controller.state.lifecycle == LifecycleState.IDLE
    controller.on_run_clicked()
    fake = controller._test_fake_runner  # type: ignore[attr-defined]
    assert len(fake.run_calls) == 1
    assert controller.state.lifecycle == LifecycleState.IDLE
    log = _get_log_text(controller)
    assert "pipeline started" in log
    assert "pipeline finished" in log


def test_second_run_after_first_completes_succeeds(controller: AppController):
    fake = controller._test_fake_runner  # type: ignore[attr-defined]

    controller.on_run_clicked()
    controller.on_run_clicked()

    assert len(fake.run_calls) == 2
    assert controller.state.lifecycle == LifecycleState.IDLE


def test_stop_sets_cancel_and_updates_lifecycle(tk_root):
    window = MainWindow(tk_root)
    fake_runner = FakePipelineRunner(simulate_long_run=True)
    controller = AppController(window, pipeline_runner=fake_runner, threaded=False)

    assert controller.state.lifecycle == LifecycleState.IDLE
    controller.on_run_clicked()
    assert controller.state.lifecycle == LifecycleState.RUNNING

    controller.on_stop_clicked()
    # After stop, for synchronous mode, we expect to end in IDLE
    assert controller.state.lifecycle == LifecycleState.IDLE
    fake = fake_runner
    assert len(fake.run_calls) == 1
    log = _get_log_text(controller)
    assert "Stop requested" in log or "stop" in log.lower()


def test_pipeline_error_sets_error_state_and_recovers(tk_root):
    window = MainWindow(tk_root)
    fake_runner = FakePipelineRunner(should_raise=True)
    controller = AppController(window, pipeline_runner=fake_runner, threaded=False)

    controller.on_run_clicked()

    # Depending on implementation, controller may go to ERROR then back to IDLE.
    # At minimum, last_error should be set and lifecycle should not remain RUNNING.
    assert controller.state.lifecycle in {LifecycleState.ERROR, LifecycleState.IDLE}
    assert controller.state.last_error is not None
    log = _get_log_text(controller)
    assert "Pipeline error" in log or "error" in log.lower()
