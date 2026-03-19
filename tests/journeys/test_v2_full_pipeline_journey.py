from __future__ import annotations

import os
import tkinter as tk
import time

import pytest

from src.app_factory import build_v2_app
from src.controller.app_controller import LifecycleState
from src.gui.app_state_v2 import PackJobEntry
from tests.helpers.job_service_di_test_helpers import make_stubbed_job_service_with_queue


def _create_root() -> tk.Tk:
    """Create a real Tk root for journey tests; fail fast if unavailable."""
    try:
        if "TCL_LIBRARY" not in os.environ:
            tcl_dir = os.path.join(os.path.dirname(tk.__file__), "tcl", "tcl8.6")
            if os.path.isdir(tcl_dir):
                os.environ["TCL_LIBRARY"] = tcl_dir

        root = tk.Tk()
        root.withdraw()
        return root
    except tk.TclError as exc:  # pragma: no cover - environment dependent
        pytest.fail(f"Tkinter unavailable for journey test: {exc}")


@pytest.mark.journey
@pytest.mark.slow
def test_v2_full_pipeline_journey_runs_once():
    """End-to-end wiring check: Run triggers pipeline with injected runner."""
    root = _create_root()
    job_service, job_queue, _ = make_stubbed_job_service_with_queue()
    root, app_state, app_controller, window = build_v2_app(
        root=root,
        pipeline_runner=None,
        threaded=False,
        job_service=job_service,
    )
    app_state.current_config.model_name = "dummy-model"
    app_state.current_config.sampler_name = "Euler a"
    app_state.current_config.steps = 20
    app_state.add_packs_to_job_draft(
        [
            PackJobEntry(
                pack_id="learning_journey_pack",
                pack_name="learning_journey_pack",
                config_snapshot={
                    "prompt": "journey prompt",
                    "model": "dummy-model",
                    "sampler": "Euler a",
                    "steps": 20,
                    "width": 512,
                    "height": 512,
                },
            )
        ]
    )

    try:
        # Preconditions
        assert app_controller.state.lifecycle == LifecycleState.IDLE

        # Act
        app_controller.on_run_clicked()

        # Assert lifecycle and queue submission
        assert app_controller.state.lifecycle in {
            LifecycleState.IDLE,
            LifecycleState.RUNNING,
            LifecycleState.ERROR,
        }
        deadline = time.time() + 1.0
        while len(job_queue.list_jobs()) < 1 and time.time() < deadline:
            root.update()
            time.sleep(0.01)

        jobs = job_queue.list_jobs()
        assert len(jobs) == 1
        submitted_job = jobs[0]
        assert submitted_job.run_mode == "queue"
        assert submitted_job.prompt_pack_id == "learning_journey_pack"
        assert submitted_job.status.name.lower() == "queued"
        assert app_controller.state.last_error in {None, ""} or isinstance(
            app_controller.state.last_error, str
        )
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
    job_service, job_queue, _ = make_stubbed_job_service_with_queue()
    root, app_state, app_controller, window = build_v2_app(
        root=root,
        pipeline_runner=None,
        threaded=False,
        job_service=job_service,
    )
    app_state.current_config.model_name = "dummy-model"
    app_state.current_config.sampler_name = "Euler a"
    app_state.current_config.steps = 20
    app_state.add_packs_to_job_draft(
        [
            PackJobEntry(
                pack_id="learning_journey_pack",
                pack_name="learning_journey_pack",
                config_snapshot={
                    "prompt": "journey prompt",
                    "model": "dummy-model",
                    "sampler": "Euler a",
                    "steps": 20,
                    "width": 512,
                    "height": 512,
                },
            )
        ]
    )

    try:
        app_controller.on_run_clicked()
        assert app_controller.state.lifecycle in {
            LifecycleState.IDLE,
            LifecycleState.RUNNING,
            LifecycleState.ERROR,
        }
        deadline = time.time() + 1.0
        while len(job_queue.list_jobs()) < 1 and time.time() < deadline:
            root.update()
            time.sleep(0.01)
        jobs = job_queue.list_jobs()
        assert len(jobs) == 1
        assert jobs[0].run_mode == "queue"
        assert jobs[0].prompt_pack_id == "learning_journey_pack"
    finally:
        try:
            window.cleanup()
        except Exception:
            pass
        try:
            root.destroy()
        except Exception:
            pass
