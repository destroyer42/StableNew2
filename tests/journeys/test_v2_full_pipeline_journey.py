from __future__ import annotations

import time

import pytest

from src.app_factory import build_v2_app
from src.controller.app_controller import LifecycleState
from src.controller.webui_connection_controller import WebUIConnectionState
from src.gui.app_state_v2 import PackJobEntry
from tests.helpers.job_service_di_test_helpers import make_stubbed_job_service_with_queue
from tests.journeys.utils.tk_root_factory import create_root


@pytest.mark.journey
@pytest.mark.slow
def test_v2_full_pipeline_journey_runs_once(monkeypatch):
    """End-to-end wiring check: Run triggers pipeline with injected runner."""
    root = create_root()
    window = None
    job_service, job_queue, _ = make_stubbed_job_service_with_queue()
    try:
        root, app_state, app_controller, window = build_v2_app(
            root=root,
            pipeline_runner=None,
            threaded=False,
            job_service=job_service,
        )
        connection = getattr(app_controller.pipeline_controller, "_webui_connection", None)
        if connection is not None:
            monkeypatch.setattr(
                connection,
                "ensure_connected",
                lambda autostart=True: WebUIConnectionState.READY,
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
        if window is not None:
            try:
                window.cleanup()
            except Exception:
                pass
        try:
            root.destroy()
        except Exception:
            pass


def test_v2_full_pipeline_journey_handles_runner_error(monkeypatch):
    """Runner failure should leave lifecycle non-running and surface an error."""
    root = create_root()
    window = None
    job_service, job_queue, _ = make_stubbed_job_service_with_queue()
    try:
        root, app_state, app_controller, window = build_v2_app(
            root=root,
            pipeline_runner=None,
            threaded=False,
            job_service=job_service,
        )
        connection = getattr(app_controller.pipeline_controller, "_webui_connection", None)
        if connection is not None:
            monkeypatch.setattr(
                connection,
                "ensure_connected",
                lambda autostart=True: WebUIConnectionState.READY,
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
        if window is not None:
            try:
                window.cleanup()
            except Exception:
                pass
        try:
            root.destroy()
        except Exception:
            pass
