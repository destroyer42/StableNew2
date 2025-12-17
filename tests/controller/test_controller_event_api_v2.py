from types import MethodType, SimpleNamespace
from typing import Any

from src.controller.app_controller import AppController, RunMode, RunSource


class DummyPipelineController:
    def __init__(self) -> None:
        self.enqueued_run_configs: list[dict[str, Any] | None] = []
        self.clear_calls = 0
        self.refresh_calls = 0
        self.replay_calls: list[str] = []

    def enqueue_draft_jobs(self, *, run_config: dict[str, Any] | None = None) -> int:
        self.enqueued_run_configs.append(run_config)
        return len(self.enqueued_run_configs)

    def clear_draft(self) -> None:
        self.clear_calls += 1

    def refresh_preview_from_state(self) -> None:
        self.refresh_calls += 1

    def replay_job_from_history(self, job_id: str) -> int:
        self.replay_calls.append(job_id)
        return len(self.replay_calls)


def _legacy_run(self, *args, **kwargs) -> str:
    self._start_run_v2_calls += 1
    self._start_run_v2_args = (args, kwargs)
    return "legacy-run"


def make_event_controller(pipeline_controller: DummyPipelineController | None) -> AppController:
    controller = object.__new__(AppController)
    controller.pipeline_controller = pipeline_controller
    job_draft = SimpleNamespace(pack_id="")
    pipeline_state = SimpleNamespace(run_mode="")
    controller.app_state = SimpleNamespace(job_draft=job_draft, pipeline_state=pipeline_state)
    controller._last_run_config = {}
    controller._append_log = lambda text: None
    controller._build_run_config = MethodType(AppController._build_run_config, controller)
    controller._ensure_run_mode_default = MethodType(
        AppController._ensure_run_mode_default, controller
    )
    controller._prepare_queue_run_config = MethodType(
        AppController._prepare_queue_run_config, controller
    )
    controller._start_run_v2_calls = 0
    controller._start_run_v2 = MethodType(_legacy_run, controller)
    return controller


def test_on_run_job_now_v2_invokes_explicit_event() -> None:
    controller = make_event_controller(DummyPipelineController())
    controller._run_now_called = False

    def run_now(self: AppController) -> str:
        controller._run_now_called = True
        return "run-now"

    controller.on_run_now = MethodType(run_now, controller)
    result = controller.on_run_job_now_v2()
    assert controller._run_now_called is True
    assert result == "run-now"


def test_on_add_to_queue_updates_run_config_and_uses_pipeline_controller() -> None:
    pipeline_controller = DummyPipelineController()
    controller = make_event_controller(pipeline_controller)
    controller.on_add_to_queue()
    assert pipeline_controller.enqueued_run_configs, (
        "PipelineController should receive a run config"
    )
    run_config = pipeline_controller.enqueued_run_configs[-1]
    assert run_config is not None
    assert run_config["run_mode"] == RunMode.QUEUE.value
    assert run_config["source"] == RunSource.ADD_TO_QUEUE_BUTTON.value
    assert controller._last_run_config == run_config


def test_on_add_job_to_queue_v2_falls_back_to_legacy_when_pipeline_controller_missing() -> None:
    controller = make_event_controller(None)
    controller.on_add_job_to_queue_v2()
    assert controller._start_run_v2_calls == 1
    assert controller._last_run_config["run_mode"] == RunMode.QUEUE.value


def test_on_clear_draft_delegates_to_pipeline_controller() -> None:
    pipeline_controller = DummyPipelineController()
    controller = make_event_controller(pipeline_controller)
    controller.on_clear_draft()
    assert pipeline_controller.clear_calls == 1


def test_on_replay_history_job_v2_uses_pipeline_controller() -> None:
    pipeline_controller = DummyPipelineController()
    controller = make_event_controller(pipeline_controller)
    success = controller.on_replay_history_job_v2("job-123")
    assert success
    assert pipeline_controller.replay_calls == ["job-123"]
