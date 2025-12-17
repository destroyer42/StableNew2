from __future__ import annotations

from typing import Any

from src.controller.app_controller import AppController, RunConfigDict, RunMode, RunSource


class FakePipelineController:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._last_run_config: dict[str, Any] | None = None

    def start_pipeline(self, *args: Any, **kwargs: Any) -> bool:
        self.calls.append({"args": args, "kwargs": kwargs})
        # Store run_config like the real PipelineController does
        if "run_config" in kwargs:
            self._last_run_config = kwargs["run_config"]
        return True


class DummyAppState:
    class PipelineState:
        run_mode = ""

    class JobDraft:
        pack_id = ""

    def __init__(self) -> None:
        self.pipeline_state = self.PipelineState()
        self.job_draft = self.JobDraft()


class DummyAppController(AppController):
    def __init__(self, pipeline_controller: Any | None = None) -> None:
        self.app_state = DummyAppState()
        self.pipeline_controller = pipeline_controller
        self.main_window = None
        self.job_service = None
        self._append_log = lambda *_: None

    # Override inherited handlers to ensure on_add_job_to_queue_v2 falls through to _start_run_v2
    on_add_job_to_queue = None
    on_add_to_queue = None


def assert_last_run_config(
    controller: DummyAppController, expected_mode: str, expected_source: str
) -> RunConfigDict:
    assert controller.pipeline_controller is not None
    fake = controller.pipeline_controller
    assert fake.calls, "start_pipeline should have been called"
    run_config = fake.calls[-1]["kwargs"]["run_config"]
    assert run_config["run_mode"] == expected_mode
    assert run_config["source"] == expected_source
    return run_config


def test_start_run_v2_passes_direct_mode_and_run_source():
    controller = DummyAppController(FakePipelineController())
    controller.start_run_v2()
    assert_last_run_config(controller, RunMode.DIRECT.value, RunSource.RUN_BUTTON.value)
    assert controller.app_state.pipeline_state.run_mode == RunMode.DIRECT.value
    assert controller.pipeline_controller._last_run_config["run_mode"] == RunMode.DIRECT.value


def test_on_run_job_now_v2_passes_queue_mode_and_run_now_source():
    controller = DummyAppController(FakePipelineController())
    controller.on_run_job_now_v2()
    assert_last_run_config(controller, RunMode.QUEUE.value, RunSource.RUN_NOW_BUTTON.value)
    assert controller.app_state.pipeline_state.run_mode == RunMode.QUEUE.value
    assert controller.pipeline_controller._last_run_config["run_mode"] == RunMode.QUEUE.value


def test_on_add_job_to_queue_v2_uses_queue_mode_and_add_source():
    controller = DummyAppController(FakePipelineController())
    controller.on_add_job_to_queue_v2()
    assert_last_run_config(controller, RunMode.QUEUE.value, RunSource.ADD_TO_QUEUE_BUTTON.value)
    assert controller.app_state.pipeline_state.run_mode == RunMode.QUEUE.value
    assert (
        controller.pipeline_controller._last_run_config["source"]
        == RunSource.ADD_TO_QUEUE_BUTTON.value
    )


def test_run_config_reports_prompt_pack_when_present():
    controller = DummyAppController(FakePipelineController())
    controller.app_state.job_draft.pack_id = "pack-xyz"
    controller.start_run_v2()
    run_config = assert_last_run_config(
        controller, RunMode.DIRECT.value, RunSource.RUN_BUTTON.value
    )
    assert run_config["prompt_source"] == "pack"
    assert run_config["prompt_pack_id"] == "pack-xyz"
