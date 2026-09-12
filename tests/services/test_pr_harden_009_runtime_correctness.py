from __future__ import annotations

import time
from types import SimpleNamespace

from src.api.client import DEFAULT_GENERATION_TIMEOUT, STALL_INTERRUPT_THRESHOLD_SEC, SDWebUIClient
from src.controller.core_pipeline_controller import CorePipelineController
from src.services.watchdog_system_v2 import SystemWatchdogV2


class _Diagnostics:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def build_async(self, **kwargs) -> None:
        self.calls.append(kwargs)
        callback = kwargs.get("on_done")
        if callable(callback):
            callback()


def _app(*, owner_id: str = "running-1", status_id: str | None = None) -> SimpleNamespace:
    owner = SimpleNamespace(job_id=owner_id, current_stage="txt2img")
    status = SimpleNamespace(
        job_id=status_id if status_id is not None else owner_id,
        current_stage="txt2img",
        stage_detail="inference",
        current_step=10,
        total_steps=36,
        progress=0.25,
    )
    app = SimpleNamespace(
        last_ui_heartbeat_ts=time.monotonic(),
        last_queue_activity_ts=time.monotonic(),
        last_runner_activity_ts=time.monotonic() - SystemWatchdogV2.RUNNER_STALL_S - 1,
        _last_runtime_status=status,
        job_service=SimpleNamespace(runner=SimpleNamespace(current_job=owner)),
        app_state=SimpleNamespace(running_job=SimpleNamespace(job_id="queued-next")),
        has_running_jobs=lambda: True,
        get_queue_state=lambda: {"running": 1},
        _is_shutting_down=False,
    )
    app.notify_runner_activity = lambda: setattr(app, "last_runner_activity_ts", time.monotonic())
    return app


def _runner_calls(diagnostics: _Diagnostics) -> list[dict[str, object]]:
    return [call for call in diagnostics.calls if call["reason"] == "queue_runner_stall"]


def test_periodic_meaningful_webui_progress_prevents_runner_stall() -> None:
    app = _app()
    diagnostics = _Diagnostics()
    watchdog = SystemWatchdogV2(app, diagnostics)

    watchdog._check()
    for step, progress in ((11, 0.30), (12, 0.35), (13, 0.40)):
        app._last_runtime_status.current_step = step
        app._last_runtime_status.progress = progress
        watchdog._last_runtime_progress_ts = time.monotonic() - SystemWatchdogV2.RUNNER_STALL_S - 1
        watchdog._check()

    assert not _runner_calls(diagnostics)


def test_frozen_execution_emits_one_bounded_runner_stall_episode() -> None:
    app = _app()
    diagnostics = _Diagnostics()
    watchdog = SystemWatchdogV2(app, diagnostics)

    watchdog._check()
    watchdog._last_runtime_progress_ts = time.monotonic() - SystemWatchdogV2.RUNNER_STALL_S - 1
    watchdog._check()
    watchdog._check()

    assert len(_runner_calls(diagnostics)) == 1


def test_periodic_native_svd_inference_progress_prevents_runner_stall() -> None:
    app = _app()
    app._last_runtime_status.current_stage = "svd_native"
    app._last_runtime_status.stage_detail = "inference"
    diagnostics = _Diagnostics()
    watchdog = SystemWatchdogV2(app, diagnostics)

    watchdog._check()
    for step, progress in ((11, 0.30), (12, 0.35), (13, 0.40)):
        app._last_runtime_status.current_step = step
        app._last_runtime_status.progress = progress
        watchdog._last_runtime_progress_ts = time.monotonic() - 301.0
        watchdog._check()

    assert not _runner_calls(diagnostics)


def test_watchdog_context_uses_runner_owned_job_not_next_queued_job() -> None:
    app = _app(status_id="queued-next")
    diagnostics = _Diagnostics()
    watchdog = SystemWatchdogV2(app, diagnostics)

    watchdog._check()

    call = _runner_calls(diagnostics)[0]
    context = call["context"]
    assert context["job_id"] == "running-1"
    assert context["execution_owner_job_id"] == "running-1"
    assert context["job_id"] != app.app_state.running_job.job_id


def test_svd_inference_uses_a_bounded_stage_specific_threshold() -> None:
    app = _app()
    app._last_runtime_status.current_stage = "svd_native"
    app._last_runtime_status.stage_detail = "inference"
    watchdog = SystemWatchdogV2(app, _Diagnostics())

    assert watchdog._runner_stall_threshold(app._last_runtime_status) == 300.0


def test_duplicate_progress_report_does_not_refresh_runner_activity() -> None:
    app = _app()
    controller = CorePipelineController(app_controller=app)

    controller.report_progress("txt2img", 50.0, "30s")
    first_activity = app.last_runner_activity_ts
    app.last_runner_activity_ts = first_activity - 10.0
    controller.report_progress("txt2img", 50.0, "29s")

    assert app.last_runner_activity_ts == first_activity - 10.0


def test_generation_response_timeout_is_bounded_but_not_the_old_short_limit() -> None:
    client = SDWebUIClient()

    assert client.timeout == 600.0
    assert DEFAULT_GENERATION_TIMEOUT == 600.0
    assert STALL_INTERRUPT_THRESHOLD_SEC < client.timeout
