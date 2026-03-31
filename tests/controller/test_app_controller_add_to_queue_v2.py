from __future__ import annotations

from types import MethodType, SimpleNamespace
from typing import Any

from src.controller.app_controller import AppController


class DummyAddToQueueHandler:
    def __init__(self) -> None:
        self.calls = 0

    def on_add_job_to_queue(self) -> None:
        self.calls += 1


def _build_controller(**kwargs: Any) -> AppController:
    class _AppState:
        def __init__(self) -> None:
            self.job_draft = SimpleNamespace(pack_id="")
            self.pipeline_state = SimpleNamespace(run_mode="")
            self.preview_jobs: list[Any] = list(kwargs.get("preview_jobs") or [])

        def clear_job_draft(self) -> None:
            self.job_draft = SimpleNamespace(pack_id="")

        def set_preview_jobs(self, jobs) -> None:
            self.preview_jobs = list(jobs or [])

    controller = object.__new__(AppController)
    controller.pipeline_controller = kwargs.get("pipeline_controller")
    controller.app_state = _AppState()
    controller._last_run_config = {}
    controller._append_log = lambda text: None
    controller._ui_dispatch = lambda fn: fn()
    controller._queue_submit_in_progress = False
    controller._is_shutting_down = False
    controller._spawn_tracked_thread = (
        lambda *, target, args=(), kwargs=None, name=None, purpose=None, daemon=False: target(
            *args, **(kwargs or {})
        )
    )
    controller._build_run_config = MethodType(AppController._build_run_config, controller)
    controller._ensure_run_mode_default = MethodType(
        AppController._ensure_run_mode_default, controller
    )
    controller._prepare_queue_run_config = MethodType(
        AppController._prepare_queue_run_config, controller
    )
    controller._submit_preview_jobs_to_queue_async = MethodType(
        AppController._submit_preview_jobs_to_queue_async, controller
    )
    return controller


def test_on_add_job_to_queue_v2_noops_when_pipeline_controller_missing():
    controller = _build_controller(pipeline_controller=None)
    handler = DummyAddToQueueHandler()
    controller.on_add_job_to_queue = handler.on_add_job_to_queue  # type: ignore[attr-defined]

    controller.on_add_job_to_queue_v2()

    assert handler.calls == 0


def test_on_add_job_to_queue_v2_noop_without_handler():
    controller = _build_controller(pipeline_controller=None)

    controller.on_add_job_to_queue_v2()

    assert True


def test_on_add_job_to_queue_v2_prefers_pipeline_controller():
    class DummyPipelineCtrl:
        def __init__(self) -> None:
            self.calls = 0

        def enqueue_draft_jobs(self, **kwargs: Any) -> int:
            self.calls += 1
            return 1

    pipeline_ctrl = DummyPipelineCtrl()
    controller = _build_controller(pipeline_controller=pipeline_ctrl)

    controller.on_add_job_to_queue_v2()

    assert pipeline_ctrl.calls == 1


def test_on_add_job_to_queue_v2_does_not_fall_back_when_preview_jobs_missing():
    class DummyPipelineCtrl:
        def enqueue_draft_jobs(self, **kwargs: Any) -> int:
            return 0

    handler = DummyAddToQueueHandler()
    controller = _build_controller(pipeline_controller=DummyPipelineCtrl())
    controller.on_add_job_to_queue = handler.on_add_job_to_queue  # type: ignore[attr-defined]

    controller.on_add_job_to_queue_v2()

    assert handler.calls == 0


def test_on_add_job_to_queue_v2_submits_preview_jobs_in_background_and_clears_preview():
    class DummyPipelineCtrl:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def submit_preview_jobs_to_queue(self, **kwargs: Any) -> int:
            self.calls.append(kwargs)
            return 2

    preview_jobs = [SimpleNamespace(job_id="job-1"), SimpleNamespace(job_id="job-2")]
    pipeline_ctrl = DummyPipelineCtrl()
    controller = _build_controller(
        pipeline_controller=pipeline_ctrl,
        preview_jobs=preview_jobs,
    )

    controller.on_add_job_to_queue_v2()

    assert len(pipeline_ctrl.calls) == 1
    assert pipeline_ctrl.calls[0]["records"] == preview_jobs
    assert controller.app_state.preview_jobs == []
    assert controller._queue_submit_in_progress is False


def test_on_add_job_to_queue_v2_ignores_requests_during_shutdown() -> None:
    class DummyPipelineCtrl:
        def __init__(self) -> None:
            self.calls = 0

        def enqueue_draft_jobs(self, **kwargs: Any) -> int:
            self.calls += 1
            return 1

    pipeline_ctrl = DummyPipelineCtrl()
    controller = _build_controller(pipeline_controller=pipeline_ctrl)
    controller._is_shutting_down = True

    controller.on_add_job_to_queue_v2()

    assert pipeline_ctrl.calls == 0
    assert controller._queue_submit_in_progress is False


def test_submit_preview_jobs_to_queue_async_skips_when_shutdown_started() -> None:
    preview_jobs = [SimpleNamespace(job_id="job-1")]

    def _should_not_clear(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("should not clear preview during shutdown")

    app_state = SimpleNamespace(
        preview_jobs=list(preview_jobs),
        clear_job_draft=_should_not_clear,
        set_preview_jobs=_should_not_clear,
    )
    pipeline_ctrl = SimpleNamespace(
        submit_preview_jobs_to_queue=lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("should not submit during shutdown")
        ),
        enqueue_draft_jobs=lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("should not enqueue during shutdown")
        ),
    )
    controller = _build_controller(pipeline_controller=pipeline_ctrl, preview_jobs=preview_jobs)
    controller.app_state = app_state
    messages: list[str] = []
    controller._append_log = lambda text: messages.append(text)
    controller._queue_submit_in_progress = True
    controller._is_shutting_down = True

    controller._submit_preview_jobs_to_queue_async(
        pipeline_ctrl,
        preview_jobs,
        {"run_mode": "queue"},
        "MainThread",
    )

    assert controller._queue_submit_in_progress is False
    assert messages == []


def test_submit_preview_jobs_to_queue_async_does_not_ui_dispatch_finish_during_shutdown() -> None:
    preview_jobs = [SimpleNamespace(job_id="job-1")]
    pipeline_ctrl = SimpleNamespace(
        submit_preview_jobs_to_queue=lambda **kwargs: 0,
    )
    controller = _build_controller(pipeline_controller=pipeline_ctrl, preview_jobs=preview_jobs)
    controller._is_shutting_down = True
    controller._queue_submit_in_progress = True
    controller._ui_dispatch = lambda fn: (_ for _ in ()).throw(
        AssertionError("shutdown path should not marshal finish via UI dispatcher")
    )

    controller._submit_preview_jobs_to_queue_async(
        pipeline_ctrl,
        preview_jobs,
        {"run_mode": "queue"},
        "MainThread",
    )

    assert controller._queue_submit_in_progress is False


def test_submit_preview_jobs_to_queue_async_preserves_preview_after_partial_submission() -> None:
    preview_jobs = [SimpleNamespace(job_id="job-1"), SimpleNamespace(job_id="job-2")]
    cleared: list[str] = []
    app_state = SimpleNamespace(
        preview_jobs=list(preview_jobs),
        clear_job_draft=lambda: cleared.append("draft"),
        set_preview_jobs=lambda jobs: cleared.append(f"preview:{len(list(jobs))}"),
    )
    pipeline_ctrl = SimpleNamespace(
        submit_preview_jobs_to_queue=lambda **kwargs: 1,
        get_last_preview_queue_submission_result=lambda: SimpleNamespace(
            remaining_record_ids=("job-2",),
        ),
    )
    controller = _build_controller(pipeline_controller=pipeline_ctrl, preview_jobs=preview_jobs)
    controller.app_state = app_state
    messages: list[str] = []
    controller._append_log = lambda text: messages.append(text)
    controller._queue_submit_in_progress = True

    controller._submit_preview_jobs_to_queue_async(
        pipeline_ctrl,
        preview_jobs,
        {"run_mode": "queue"},
        "MainThread",
    )

    assert controller._queue_submit_in_progress is False
    assert cleared == ["preview:1"]
    assert any("1 preview job(s) remain" in message for message in messages)
