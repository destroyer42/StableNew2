from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import Mock

from src.controller.app_controller import AppController
from src.controller.core_pipeline_controller import CorePipelineController
from src.controller.job_service import JobService
from src.services.watchdog_system_v2 import SystemWatchdogV2
from src.queue.job_queue import JobQueue
from src.queue.job_repository import JobRepository
from src.utils.config import ConfigManager


class _Diagnostics:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def build_async(self, **kwargs) -> None:
        self.calls.append(kwargs)
        callback = kwargs.get("on_done")
        if callable(callback):
            callback()


def _running_app(*, runner_age_s: float, job_id: str = "job-1") -> SimpleNamespace:
    app = SimpleNamespace(
        last_ui_heartbeat_ts=time.monotonic(),
        last_queue_activity_ts=time.monotonic(),
        last_runner_activity_ts=time.monotonic() - runner_age_s,
        _last_runtime_status=SimpleNamespace(
            job_id=job_id,
            current_stage="txt2img",
            progress=0.5,
        ),
        has_running_jobs=lambda: True,
        get_queue_state=lambda: {"running": 1},
        _is_shutting_down=False,
    )
    app.notify_runner_activity = lambda: setattr(app, "last_runner_activity_ts", time.monotonic())
    return app


def test_idle_application_then_running_job_refreshes_runner_age() -> None:
    app = _running_app(runner_age_s=30 * 60)
    diagnostics = _Diagnostics()
    watchdog = SystemWatchdogV2(app, diagnostics)

    app.last_runner_activity_ts = time.monotonic()
    watchdog._check()

    assert not any(call["reason"] == "queue_runner_stall" for call in diagnostics.calls)


def test_healthy_runtime_activity_keeps_long_running_job_out_of_stall() -> None:
    app = _running_app(runner_age_s=0)
    diagnostics = _Diagnostics()
    watchdog = SystemWatchdogV2(app, diagnostics)

    for _ in range(4):
        app.last_runner_activity_ts = time.monotonic()
        watchdog._check()

    assert not any(call["reason"] == "queue_runner_stall" for call in diagnostics.calls)


def test_runtime_progress_activity_refreshes_watchdog_runner_age() -> None:
    app = _running_app(runner_age_s=SystemWatchdogV2.RUNNER_STALL_S + 1)
    diagnostics = _Diagnostics()
    watchdog = SystemWatchdogV2(app, diagnostics)
    progress_controller = CorePipelineController(app_controller=app)

    progress_controller.report_progress("txt2img", 50.0, "30s")
    watchdog._check()

    assert not any(call["reason"] == "queue_runner_stall" for call in diagnostics.calls)


def test_inactive_runner_reports_context_and_one_episode() -> None:
    app = _running_app(runner_age_s=SystemWatchdogV2.RUNNER_STALL_S + 1)
    diagnostics = _Diagnostics()
    watchdog = SystemWatchdogV2(app, diagnostics)

    watchdog._check()
    watchdog._check()

    runner_calls = [call for call in diagnostics.calls if call["reason"] == "queue_runner_stall"]
    assert len(runner_calls) == 1
    context = runner_calls[0]["context"]
    assert context["job_id"] == "job-1"
    assert context["current_stage"] == "txt2img"
    assert context["latest_progress"] == 0.5
    assert context["runner_activity_age_s"] > SystemWatchdogV2.RUNNER_STALL_S


def test_stall_episode_deduplicates_beyond_cooldown_and_resets_after_activity() -> None:
    app = _running_app(runner_age_s=SystemWatchdogV2.RUNNER_STALL_S + 1)
    diagnostics = _Diagnostics()
    watchdog = SystemWatchdogV2(app, diagnostics)

    watchdog._check()
    watchdog._last_trigger_ts["queue_runner_stall"] -= 2 * SystemWatchdogV2.COOLDOWN_S["queue_runner_stall"]
    watchdog._check()
    assert len([call for call in diagnostics.calls if call["reason"] == "queue_runner_stall"]) == 1

    app.last_runner_activity_ts = time.monotonic()
    watchdog._check()
    app.last_runner_activity_ts = time.monotonic() - SystemWatchdogV2.RUNNER_STALL_S - 1
    watchdog._check()

    assert len([call for call in diagnostics.calls if call["reason"] == "queue_runner_stall"]) == 2


def test_production_composition_binds_watchdog_to_canonical_service_runner_queue(tmp_path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    queue = JobQueue(repository=repository)
    service = JobService(queue, run_callable=None, require_normalized_records=True)
    app = AppController(
        main_window=None,
        threaded=False,
        pipeline_runner=Mock(),
        api_client=Mock(),
        config_manager=ConfigManager(presets_dir=tmp_path / "presets"),
        job_service=service,
    )
    try:
        pipeline_controller = app.pipeline_controller
        assert app.job_service is service
        assert pipeline_controller.get_job_service() is service
        assert pipeline_controller._job_controller.get_runner() is service.runner
        assert service.runner.job_queue is queue
        assert getattr(service, "_on_runner_activity").__self__ is app

        app.last_runner_activity_ts = 0.0
        service.runner._on_activity()
        assert app.last_runner_activity_ts > 0.0
    finally:
        service.runner.stop()
        repository.close()
