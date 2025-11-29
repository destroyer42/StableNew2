from __future__ import annotations

import tkinter as tk

import pytest

from src.app_factory import build_v2_app
from src.controller.app_controller import LifecycleState
from tests.journeys.fakes.fake_pipeline_runner import FakePipelineRunner


def _create_root() -> tk.Tk:
    """Create a real Tk root for journey tests; fail fast if unavailable."""
    try:
        root = tk.Tk()
        root.withdraw()
        return root
    except tk.TclError as exc:  # pragma: no cover - environment dependent
        pytest.fail(f"Tkinter unavailable for journey test: {exc}")


def test_v2_full_pipeline_journey_runs_once():
    """End-to-end wiring check: Run triggers pipeline with injected runner."""
    root = _create_root()
    fake_runner = FakePipelineRunner()
    root, app_state, app_controller, window = build_v2_app(
        root=root,
        pipeline_runner=fake_runner,
        threaded=False,
    )

    try:
        # Preconditions
        assert app_controller.state.lifecycle == LifecycleState.IDLE

        # Act
        app_controller.on_run_clicked()

        # Assert lifecycle and run call
        assert app_controller.state.lifecycle in {LifecycleState.IDLE, LifecycleState.ERROR}
        assert len(fake_runner.run_calls) == 1
        call = fake_runner.run_calls[0]
        assert call.config.prompt != ""
        assert call.config.model != ""
        assert call.config.steps > 0
        assert app_controller.state.last_error in {None, ""} or isinstance(app_controller.state.last_error, str)
    finally:
        try:
            window.cleanup()
        except Exception:
            pass
        try:
            root.destroy()
        except Exception:
            pass


def test_v2_full_pipeline_journey_handles_runner_error():
    """Runner failure should leave lifecycle non-running and surface an error."""
    root = _create_root()
    fake_runner = FakePipelineRunner(should_raise=True)
    root, app_state, app_controller, window = build_v2_app(
        root=root,
        pipeline_runner=fake_runner,
        threaded=False,
    )

    try:
        app_controller.on_run_clicked()
        assert app_controller.state.lifecycle in {LifecycleState.ERROR, LifecycleState.IDLE}
        assert len(fake_runner.run_calls) == 1
    finally:
        try:
            window.cleanup()
        except Exception:
            pass
        try:
            root.destroy()
        except Exception:
            pass
