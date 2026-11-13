"""P3-2A golden wiring tests: the runtime stack's identities, construction counts/order, callbacks and recovery.

Written and run against unmodified ``main`` first; they must keep passing unchanged after the factory consolidation.
All hermetic: ``AppController(None, threaded=False, ...)`` is the construction ``build_v2_app`` takes. No WebUI, GPU,
process or network. The operator's real repository file is never opened (``:memory:`` under pytest, or a temp file).
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from typing import Any

import pytest

from src.controller.app_controller import AppController
from src.controller.job_execution_controller import JobExecutionController
from src.controller.pipeline_controller import PipelineController
from src.queue.job_history_store import INTERRUPTED_RESTART_ACTION_REQUIRED
from src.queue.job_model import Job, JobStatus
from src.queue.job_repository import JobRepository
from src.queue.single_node_runner import SingleNodeJobRunner
from src.utils.logger import StructuredLogger, close_all_structured_loggers

# ----------------------------------------------------------------------------------------------------- helpers
_TRACKED = {
    "JobRepository": "src.queue.job_repository",
    "JobQueue": "src.queue.job_queue",
    "SingleNodeJobRunner": "src.queue.single_node_runner",
    "JobService": "src.controller.job_service",
    "JobHistoryService": "src.controller.job_history_service",
    "WebUIOutageCoordinator": "src.controller.webui_outage_coordinator",
    "GpuLossCoordinator": "src.controller.gpu_loss_coordinator",
    "WebUIConnectionController": "src.controller.webui_connection_controller",
    "PipelineRunner": "src.pipeline.pipeline_runner",
    "WebUIProcessManager": "src.api.webui_process_manager",
    "ComfyProcessManager": "src.video.comfy_process_manager",
    "RuntimeHandoffGate": "src.controller.webui_runtime_handoff_gate",
}


def construction_log(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record every construction of the tracked classes, in order, plus the startup-gate call."""

    import importlib

    log: list[str] = []
    for name, module_name in _TRACKED.items():
        cls = getattr(importlib.import_module(module_name), name)
        original = cls.__init__

        def recording(self, *args, __original=original, __name=name, **kwargs):
            log.append(__name)
            __original(self, *args, **kwargs)

        monkeypatch.setattr(cls, "__init__", recording)
    from src.controller.webui_outage_coordinator import WebUIOutageCoordinator

    gate = WebUIOutageCoordinator.enable_startup_gate

    def recording_gate(self, *args, **kwargs):
        log.append("startup_gate")
        return gate(self, *args, **kwargs)

    monkeypatch.setattr(WebUIOutageCoordinator, "enable_startup_gate", recording_gate)
    return log


def make_njr_job(job_id: str) -> Job:
    from src.pipeline.cli_njr_builder import build_cli_njr

    record = build_cli_njr(
        prompt=f"prompt {job_id}",
        batch_size=1,
        run_name=job_id,
        config={
            "txt2img": {
                "model": "t.safetensors",
                "steps": 4,
                "cfg_scale": 5.0,
                "width": 64,
                "height": 64,
            }
        },
    )
    job = Job(job_id=record.job_id, snapshot={"normalized_job": record.to_dict()})
    job._normalized_record = record  # type: ignore[attr-defined]
    return job


@pytest.fixture
def production_controller(tmp_path: Path):
    """The production construction path: no injected service."""

    controller = AppController(
        None,
        threaded=False,
        structured_logger=StructuredLogger(output_dir=str(tmp_path / "structured_logs")),
    )
    try:
        yield controller
    finally:
        try:
            controller.job_service.stop()
        except Exception:
            pass
        close_all_structured_loggers()


def _parts(controller: AppController) -> tuple[Any, PipelineController, JobExecutionController]:
    pipeline = controller.pipeline_controller
    return controller.job_service, pipeline, pipeline.get_job_execution_controller()


# --------------------------------------------------------------------------------------------------------- G1
def test_g1_one_stack_one_set_of_identities(production_controller: AppController) -> None:
    service, pipeline, jec = _parts(production_controller)
    queue = jec.get_queue()
    repository = jec.get_history_store()

    assert service is pipeline.get_job_service()
    assert service.job_queue is queue
    assert service.history_store is queue.repository is repository
    assert isinstance(repository, JobRepository)
    assert service.runner is jec.get_runner()
    assert pipeline.get_job_history_service() is service._history_service
    # The coordinators are bound to that queue and observe that runner.
    assert service.webui_outage._queue is queue
    assert service.gpu_loss._queue is queue
    runner = service.runner
    assert runner._outage_observer is service.webui_outage
    assert runner._gpu_loss_observer is service.gpu_loss
    # Hermetic repository location under pytest: in memory, never the operator's file.
    assert repository.path is None


# --------------------------------------------------------------------------------------------------------- G2/G3
def test_g2_g3_construction_counts_and_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    log = construction_log(monkeypatch)
    controller = AppController(
        None,
        threaded=False,
        structured_logger=StructuredLogger(output_dir=str(tmp_path / "structured_logs")),
    )
    try:
        counts = {name: log.count(name) for name in set(log)}
        for name in (
            "JobRepository",
            "JobQueue",
            "SingleNodeJobRunner",
            "JobService",
            "JobHistoryService",
            "WebUIOutageCoordinator",
            "GpuLossCoordinator",
            "WebUIConnectionController",
        ):
            assert counts.get(name) == 1, (name, counts)
        assert counts.get("WebUIProcessManager", 0) == 0
        assert counts.get("ComfyProcessManager", 0) == 0
        assert counts.get("RuntimeHandoffGate", 0) == 0
        assert counts.get("PipelineRunner", 0) <= 1
        order = [
            name
            for name in log
            if name
            in {"JobRepository", "JobQueue", "SingleNodeJobRunner", "JobService", "startup_gate"}
        ]
        assert order == [
            "JobRepository",
            "JobQueue",
            "SingleNodeJobRunner",
            "JobService",
            "startup_gate",
        ]
        # The history service (sole repository observer) exists before the service that adopts it.
        assert log.index("JobHistoryService") < log.index("JobService")
    finally:
        try:
            controller.job_service.stop()
        finally:
            close_all_structured_loggers()


# --------------------------------------------------------------------------------------------------------- G4
def test_g4_callback_registration_and_dispatch_policy(production_controller: AppController) -> None:
    service, pipeline, jec = _parts(production_controller)
    repository = jec.get_history_store()
    queue = jec.get_queue()

    assert len(repository._callbacks) == 1  # the history service is the one repository observer
    assert set(jec._callbacks) == {"pipeline_ctrl"}
    status_keys = {
        key[len("_status_callback_") :]
        for key in service._listeners
        if key.startswith("_status_callback_")
    }
    assert status_keys == {"pipeline", "gui_queue_history"}
    assert len(queue._status_callbacks) >= 1
    assert len(service._completion_handlers) == 2  # learning + photo-optimize

    # The runner's continuous-dispatch policy follows JobService.auto_run_enabled, not the controller flag.
    runner = service.runner
    service.auto_run_enabled = True
    jec._auto_run_enabled = False
    assert runner._continuous_dispatch_allowed() is True
    service.auto_run_enabled = False
    jec._auto_run_enabled = True
    assert runner._continuous_dispatch_allowed() is False


def test_g4_listener_counts_are_stable(production_controller: AppController) -> None:
    service, _, _ = _parts(production_controller)
    counts = {event: len(callbacks) for event, callbacks in sorted(service._listeners.items())}
    assert counts == EXPECTED_LISTENER_COUNTS


# Observed on unmodified main at 67e0e559.
EXPECTED_LISTENER_COUNTS: dict[str, int] = {
    "_status_callback_gui_queue_history": 1,
    "_status_callback_pipeline": 1,
    "job_failed": 3,
    "job_finished": 3,
    "job_started": 2,
    "queue_empty": 2,
    "queue_status": 2,
    "queue_updated": 2,
    "watchdog_violation": 1,
}


# --------------------------------------------------------------------------------------------------------- G6/N7
def _seed_repository(path: Path) -> None:
    repository = JobRepository(path)
    from src.queue.job_queue import JobQueue

    queue = JobQueue(repository=repository)
    queue.submit(make_njr_job("queued-first"))
    queue.submit(make_njr_job("interrupted"))
    queue.mark_running("interrupted")
    queue.submit(make_njr_job("queued-second"))
    repository.close()


def test_g6_restart_recovery_runs_once_and_never_replays(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from src.state.workspace_paths import workspace_paths

    path = tmp_path / "state" / "jobs.sqlite3"
    path.parent.mkdir(parents=True)
    _seed_repository(path)
    # The one repository-location rule: no pytest marker -> workspace_paths.job_repository(), redirected to temp.
    monkeypatch.setattr(workspace_paths, "job_repository", lambda: path)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    log = construction_log(monkeypatch)
    calls: list[str] = []
    original_callback = JobExecutionController._run_job_callback
    monkeypatch.setattr(
        JobExecutionController,
        "_run_job_callback",
        lambda self, job: calls.append(job.job_id) or original_callback(self, job),
    )
    pipeline = PipelineController(
        pipeline_runner=None,
        structured_logger=None,
    )
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "test_g6 (call)")  # restore the marker for teardown
    try:
        jec = pipeline.get_job_execution_controller()
        repository = jec.get_history_store()
        assert repository.path == path
        assert log.count("JobRepository") == 1
        assert log.count("JobQueue") == 1  # recovery ran exactly once, at queue construction

        interrupted = jec.get_queue().get_job("interrupted")
        assert interrupted is not None and interrupted.status == JobStatus.FAILED
        envelope = interrupted.error_envelope
        assert envelope is not None
        assert envelope.error_type == INTERRUPTED_RESTART_ACTION_REQUIRED
        assert envelope.context["automatic_replay"] is False
        queued = [job.job_id for job in jec.get_queue().list_active_jobs_ordered()]
        assert queued == ["queued-first", "queued-second"]
        # Autostart is deferred: nothing is running and the worker has not started.
        assert jec._deferred_autostart is True
        assert not jec.get_runner().is_running()

        # N7: construction never reached the run callable or claimed the interrupted job.
        assert calls == []
        claimable = jec.get_queue().get_next_job()
        assert claimable is None or claimable.job_id != "interrupted"
        assert jec.get_queue().get_job("interrupted").status == JobStatus.FAILED
    finally:
        try:
            pipeline.get_job_service().stop()
        finally:
            pipeline.get_job_execution_controller().get_history_store().close()


# --------------------------------------------------------------------------------------------------------- G7
def test_g7_shutdown_closes_the_one_repository_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    closed: list[JobRepository] = []
    original_close = JobRepository.close

    def recording_close(self: JobRepository) -> None:
        closed.append(self)
        original_close(self)

    monkeypatch.setattr(JobRepository, "close", recording_close)
    log = construction_log(monkeypatch)
    controller = AppController(
        None,
        threaded=False,
        structured_logger=StructuredLogger(output_dir=str(tmp_path / "structured_logs")),
    )
    repository = controller.job_service.history_store
    controller.shutdown_app("g7")
    assert log.count("JobRepository") == 1
    assert closed == [repository]


# --------------------------------------------------------------------------------------------------------- G9
def test_g9_runtime_handoff_is_unarmed_until_main_arms_it(
    production_controller: AppController,
) -> None:
    from src.controller.job_service_outage import arm_runtime_handoff

    service = production_controller.job_service
    assert service.webui_outage._gate is None
    assert arm_runtime_handoff(service) is True
    assert service.webui_outage._gate is not None


def test_g9_an_injected_service_is_never_armed(tmp_path: Path) -> None:
    class _Injected:
        EVENT_QUEUE_UPDATED = "queue_updated"
        EVENT_QUEUE_STATUS = "queue_status"
        EVENT_JOB_STARTED = "job_started"
        EVENT_JOB_FINISHED = "job_finished"
        EVENT_JOB_FAILED = "job_failed"
        EVENT_QUEUE_EMPTY = "queue_empty"

        def __init__(self) -> None:
            from unittest import mock

            self.webui_outage = mock.MagicMock()

        def register_callback(self, *_: object, **__: object) -> None:
            pass

    injected = _Injected()
    AppController(
        None,
        threaded=False,
        job_service=injected,
        structured_logger=StructuredLogger(output_dir=str(tmp_path / "structured_logs")),
    )
    try:
        injected.webui_outage.enable_startup_gate.assert_not_called()
        injected.webui_outage.enable_runtime_handoff.assert_not_called()
    finally:
        close_all_structured_loggers()


# --------------------------------------------------------------------------------------------------------- G10
def test_g10_repository_path_attributes_are_characterized(
    production_controller: AppController, tmp_path: Path
) -> None:
    """Under pytest the controller's stored path is a unique temp file that differs from the in-memory repository."""

    import tempfile

    controller = production_controller
    path = controller._job_repository_path
    assert path is not None
    assert Path(path).parent == Path(tempfile.gettempdir())
    assert Path(path).name.startswith("stablenew_jobs_")
    assert controller._job_history_path == controller._job_repository_path
    assert not Path(path).exists()  # never created: the repository is in memory
    assert controller.job_service.history_store.path is None

    other = AppController(
        None,
        threaded=False,
        structured_logger=StructuredLogger(output_dir=str(tmp_path / "structured_logs2")),
    )
    try:
        assert other._job_repository_path != controller._job_repository_path
    finally:
        other.job_service.stop()


def test_g10_production_mode_values_use_the_workspace_repository_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from src.state.workspace_paths import workspace_paths

    expected = workspace_paths.job_repository()
    monkeypatch.setenv(
        "STABLENEW_TEST_MODE", "1"
    )  # keep the other test-mode switches on without the pytest marker
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    # The workspace path is redirected to temp before construction, so the real repository is never opened.
    monkeypatch.setattr(workspace_paths, "job_repository", lambda: tmp_path / "jobs.sqlite3")
    controller = AppController(
        None,
        threaded=False,
        structured_logger=StructuredLogger(output_dir=str(tmp_path / "structured_logs")),
    )
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "test_g10 (call)")
    try:
        assert controller._job_repository_path == tmp_path / "jobs.sqlite3"
        assert controller._job_history_path == tmp_path / "jobs.sqlite3"
        assert controller.job_service.history_store.path == tmp_path / "jobs.sqlite3"
        assert tmp_path / "jobs.sqlite3" != expected
    finally:
        controller.job_service.stop()
        controller.job_service.history_store.close()
        close_all_structured_loggers()


# --------------------------------------------------------------------------------------------------------- G11
def test_g11_replace_queue_runner_keeps_one_runner_and_the_same_coordinators(
    production_controller: AppController,
) -> None:
    service, pipeline, jec = _parts(production_controller)
    queue = jec.get_queue()
    outage, gpu = service.webui_outage, service.gpu_loss
    old_runner = service.runner
    new_runner = SingleNodeJobRunner(queue, lambda job: {"success": True}, poll_interval=0.05)

    pipeline.replace_queue_runner(new_runner)

    assert service.runner is new_runner is jec.get_runner()
    assert service.webui_outage is outage and service.gpu_loss is gpu
    assert new_runner._outage_observer is outage
    assert new_runner._gpu_loss_observer is gpu
    assert not old_runner.is_running()
    assert len(jec.get_history_store()._callbacks) == 1
    stack = getattr(pipeline, "get_runtime_stack", lambda: None)()
    if stack is not None:  # after P3-2A the record reads the live runner instead of storing one
        assert stack.runner is new_runner


# --------------------------------------------------------------------------------------------------------- G8
@pytest.fixture
def isolated_gui_workspace_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Keep ``build_v2_app`` from writing GUI state into the repository (the ``tests/gui_v2`` autouse fixture's job).

    The full window builds the Photo Optimize tab, whose store otherwise creates ``output/PhotoOptimize/workspace`` in
    the checkout; the Windows lane's repository-contents check rejects that.
    """

    import src.gui.preview_panel_v2 as preview_panel_v2
    import src.gui.sidebar_panel_v2 as sidebar_panel_v2
    import src.photo_optimize.store as photo_store
    import src.services.ui_state_store as ui_state_store

    root = tmp_path / "gui_workspace"
    monkeypatch.setattr(ui_state_store, "UI_STATE_PATH", root / "state" / "ui_state.json")
    monkeypatch.setattr(ui_state_store, "_global_store", None)
    # An injected PHOTO_OPTIMIZE_ROOT is what ``get_photo_optimize_store`` honours without migrating operator data.
    monkeypatch.setattr(photo_store, "PHOTO_OPTIMIZE_ROOT", root / "PhotoOptimize")
    monkeypatch.setattr(photo_store, "_global_store", None)
    monkeypatch.setattr(sidebar_panel_v2, "SIDEBAR_STATE_PATH", root / "state" / "sidebar_state.json")
    monkeypatch.setattr(preview_panel_v2, "PREVIEW_STATE_PATH", root / "state" / "preview_panel_state.json")
    return root


@pytest.mark.gui
def test_g8_app_state_binding_after_build_v2_app(
    tk_root: tk.Tk, isolated_gui_workspace_state: Path
) -> None:
    from src.app_factory import build_v2_app

    _, app_state, controller, window = build_v2_app(root=tk_root)
    try:
        service = controller.job_service
        assert controller.app_state is window.app_state is app_state
        assert controller.pipeline_controller._app_state is app_state
        assert controller._projection_sink._app_state is app_state
        # Characterization only (P3-2A repairs nothing): today's auto-run / pause projection on the window's state.
        observed = {
            "service_auto_run": service.auto_run_enabled,
            "app_state_auto_run": app_state.auto_run_queue,
            "queue_paused": service.job_queue.is_paused(),
            "app_state_paused": app_state.is_queue_paused,
        }
        assert observed == EXPECTED_G8_PROJECTION
    finally:
        window.cleanup()


# Observed on main: the window's state and the service agree (no projection mismatch to report).
EXPECTED_G8_PROJECTION: dict[str, bool] = {
    "service_auto_run": True,
    "app_state_auto_run": True,
    "queue_paused": False,
    "app_state_paused": False,
}
