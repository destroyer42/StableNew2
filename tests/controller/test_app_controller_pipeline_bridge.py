from __future__ import annotations

from types import SimpleNamespace

from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.controller.app_controller import AppController
from src.gui.app_state_v2 import AppStateV2
from src.controller.runtime_state import GUIState
from src.controller.webui_connection_controller import WebUIConnectionState
from src.queue.job_model import Job, JobStatus
from tests.helpers.job_service_di_test_helpers import make_stubbed_job_service


class DummyPipelineController:
    def __init__(self, *, should_raise: bool = False):
        self.start_calls = 0
        self.should_raise = should_raise
        self.last_run_config = None

    def start_pipeline(self, *args, **kwargs):
        self.start_calls += 1
        self.last_run_config = kwargs.get("run_config")
        if self.should_raise:
            raise RuntimeError("bridge failed")
        return True


def _build_controller(**kwargs) -> AppController:
    if "job_service" not in kwargs:
        kwargs["job_service"] = make_stubbed_job_service()
    main_window = kwargs.pop("main_window", None)
    controller = AppController(
        main_window=main_window,
        pipeline_runner=None,
        api_client=None,
        structured_logger=None,
        webui_process_manager=None,
        config_manager=None,
        resource_service=None,
        **kwargs,
    )
    if "pipeline_controller" not in kwargs:
        controller.pipeline_controller = None
    return controller


def _make_preview_job(job_id: str = "preview-1") -> NormalizedJobRecord:
    return NormalizedJobRecord(
        job_id=job_id,
        config={"prompt": "p"},
        path_output_dir="output",
        filename_template="{seed}",
        positive_prompt="portrait",
        negative_prompt="",
    )


class AsyncRunPipelineController:
    def __init__(self) -> None:
        self.prepare_calls: list[dict[str, object]] = []
        self.queue_submit_calls: list[dict[str, object]] = []
        self.transitions: list[GUIState] = []

    def prepare_queue_run_submission(self, *, run_config=None, source: str = "gui"):
        payload = dict(run_config or {})
        self.prepare_calls.append({"run_config": payload, "source": source})
        return SimpleNamespace(
            source=source,
            prompt_source=str(payload.get("prompt_source") or "manual"),
            run_config=payload,
        )

    def ensure_run_submission_ready(self) -> bool:
        return True

    def get_preview_jobs(self):
        return [_make_preview_job()]

    def submit_preview_jobs_to_queue(self, *, records, source: str, prompt_source: str, run_config=None):
        self.queue_submit_calls.append(
            {
                "records": list(records),
                "source": source,
                "prompt_source": prompt_source,
                "run_config": dict(run_config or {}),
            }
        )
        return len(list(records))

    def _safe_gui_transition(self, state: GUIState) -> None:
        self.transitions.append(state)


def test_start_run_v2_invokes_pipeline_controller() -> None:
    dummy = DummyPipelineController()
    controller = _build_controller(pipeline_controller=dummy)

    assert controller.start_run_v2() is True
    assert dummy.start_calls == 1
    assert dummy.last_run_config["run_mode"] == "queue"
    assert dummy.last_run_config["source"] == "run"


def test_start_run_v2_returns_false_without_pipeline_controller() -> None:
    controller = _build_controller()
    controller.pipeline_controller = None

    assert controller.start_run_v2() is False


def test_start_run_v2_returns_false_on_bridge_error() -> None:
    dummy = DummyPipelineController(should_raise=True)
    controller = _build_controller(pipeline_controller=dummy)

    assert controller.start_run_v2() is False
    assert dummy.start_calls == 1


def test_refresh_preview_from_state_async_builds_off_thread_and_applies_latest_result() -> None:
    class DummyPreviewController:
        def __init__(self) -> None:
            self.calls = 0

        def build_preview_request(self):
            return object()

        def get_preview_jobs_for_request(self, _request):
            self.calls += 1
            return [
                NormalizedJobRecord(
                    job_id="preview-1",
                    config={"prompt": "p"},
                    path_output_dir="output",
                    filename_template="{seed}",
                )
            ]

    dummy = DummyPreviewController()
    controller = _build_controller(pipeline_controller=dummy)
    controller._background_tasks._run_inline = True

    controller._refresh_preview_from_state_async()

    assert dummy.calls == 1
    assert len(controller.app_state.preview_jobs) == 1
    assert controller.app_state.preview_jobs[0].job_id == "preview-1"


def test_request_preview_refresh_marks_preview_dirty_when_gui_context_exists() -> None:
    main_window = SimpleNamespace(app_state=AppStateV2(), root=None)
    controller = _build_controller(main_window=main_window)
    calls: list[dict[str, object]] = []

    def _mark_ui_dirty(**kwargs):
        calls.append(dict(kwargs))

    controller._mark_ui_dirty = _mark_ui_dirty  # type: ignore[assignment]

    controller.request_preview_refresh()

    assert calls == [{"preview": True}]


def test_request_preview_refresh_falls_back_to_sync_without_gui_context() -> None:
    controller = _build_controller()
    calls: list[str] = []

    def _refresh_preview_from_state() -> None:
        calls.append("refresh")

    controller._refresh_preview_from_state = _refresh_preview_from_state  # type: ignore[assignment]

    controller.request_preview_refresh()

    assert calls == ["refresh"]


def test_start_run_v2_in_gui_mode_submits_queue_run_off_thread() -> None:
    main_window = SimpleNamespace(app_state=AppStateV2(), root=None)
    dummy = AsyncRunPipelineController()
    controller = _build_controller(main_window=main_window, threaded=True, pipeline_controller=dummy)
    spawn_calls: list[dict[str, object]] = []

    def _run_inline(target, args=(), kwargs=None, **_unused):
        spawn_calls.append({"target": target, "args": args, "kwargs": kwargs or {}})
        target(*args, **(kwargs or {}))

    controller._spawn_tracked_thread = _run_inline  # type: ignore[assignment]

    assert controller.start_run_v2() is True
    assert len(spawn_calls) == 1
    assert len(dummy.prepare_calls) == 1
    assert len(dummy.queue_submit_calls) == 1
    assert controller._last_run_config is not None
    assert controller._last_run_config["run_mode"] == "queue"
    assert controller._last_run_config["source"] == "run"
    assert dummy.queue_submit_calls[0]["source"] == "gui"
    assert dummy.queue_submit_calls[0]["run_config"]["source"] == "run"
    assert controller._run_submission_in_progress is False
    assert controller.current_operation_label is None


def test_refresh_app_state_queue_replays_latest_async_projection_request() -> None:
    main_window = SimpleNamespace(app_state=AppStateV2(), root=None)
    controller = _build_controller(main_window=main_window, threaded=True)
    projections = [(["first"], []), (["second"], [])]
    build_calls = 0

    def _build_projection():
        nonlocal build_calls
        result = projections[min(build_calls, len(projections) - 1)]
        build_calls += 1
        return result

    controller._background_tasks._run_inline = True
    controller._runtime_projection_coordinator._build_queue_projection = _build_projection  # type: ignore[attr-defined]

    controller._refresh_app_state_queue()
    controller._refresh_app_state_queue()

    assert build_calls == 2
    assert controller.app_state.queue_items == ["second"]


def test_refresh_app_state_queue_in_gui_mode_applies_built_queue_jobs() -> None:
    main_window = SimpleNamespace(app_state=AppStateV2(), root=None)
    controller = _build_controller(main_window=main_window, threaded=True)
    job = Job(job_id="job-running")
    job.status = JobStatus.RUNNING
    job._normalized_record = _make_preview_job(job.job_id)  # type: ignore[attr-defined]
    controller.job_service.queue.submit(job)
    controller._background_tasks._run_inline = True

    controller._refresh_app_state_queue()

    assert controller.app_state.queue_jobs
    assert controller.app_state.queue_jobs[0].job_id == "job-running"
    assert controller.app_state.queue_jobs[0].status == "RUNNING"


def test_get_diagnostics_snapshot_includes_runtime_timing_data() -> None:
    controller = _build_controller()
    controller._last_queue_projection_timing = {"elapsed_ms": 12.5, "job_count": 2}
    controller.webui_connection_controller = SimpleNamespace(
        get_last_connection_timing_snapshot=lambda: {"total_elapsed_ms": 56.0},
        get_state=lambda: WebUIConnectionState.READY,
    )
    controller.pipeline_controller = SimpleNamespace(
        get_preview_build_timing_snapshot=lambda: {"elapsed_ms": 34.0, "job_count": 1},
    )

    snapshot = controller.get_diagnostics_snapshot()

    assert snapshot["controller"]["queue_projection_timing"]["elapsed_ms"] == 12.5
    assert snapshot["pipeline_controller"]["preview_build_timing"]["elapsed_ms"] == 34.0
    assert snapshot["webui_connection"]["state"] == "ready"
    assert snapshot["webui_connection"]["timing"]["total_elapsed_ms"] == 56.0
