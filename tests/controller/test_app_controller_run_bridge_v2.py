import pytest

from src.controller.app_controller import AppController, RunMode, RunSource


class DummyAppState:
    def __init__(self) -> None:
        self.pipeline_state = type("PS", (), {"run_mode": ""})()
        self.job_draft = type("JD", (), {"pack_id": ""})()


class DummyController(AppController):
    def __init__(self) -> None:
        self.app_state = DummyAppState()
        self._last_run_config = None
        self._log: list[str] = []
        self.start_run = lambda: None
        self.run_pipeline_v2_bridge = lambda: True

    def _append_log(self, message: str) -> None:
        self._log.append(message)


@pytest.fixture
def controller() -> AppController:
    return DummyController()


def test_start_run_v2_sets_direct_mode_and_source(controller: AppController) -> None:
    controller.start_run_v2()

    run_config = getattr(controller, "_last_run_config", {})
    assert run_config.get("run_mode") == RunMode.DIRECT.value
    assert run_config.get("source") == RunSource.RUN_BUTTON.value
    assert controller.app_state.pipeline_state.run_mode == RunMode.DIRECT.value


def test_on_run_job_now_v2_sets_queue_mode(controller: AppController) -> None:
    controller.on_run_job_now_v2()

    run_config = getattr(controller, "_last_run_config", {})
    assert run_config.get("run_mode") == RunMode.QUEUE.value
    assert run_config.get("source") == RunSource.RUN_NOW_BUTTON.value
    assert controller.app_state.pipeline_state.run_mode == RunMode.QUEUE.value


def test_on_add_job_to_queue_v2_sets_queue_mode(controller: AppController) -> None:
    controller.on_add_job_to_queue_v2()

    run_config = getattr(controller, "_last_run_config", {})
    assert run_config.get("run_mode") == RunMode.QUEUE.value
    assert run_config.get("source") == RunSource.ADD_TO_QUEUE_BUTTON.value
    assert controller.app_state.pipeline_state.run_mode == RunMode.QUEUE.value


def test_run_config_detects_prompt_pack(controller: AppController) -> None:
    controller.app_state.job_draft.pack_id = "pack-123"

    controller.start_run_v2()

    run_config = getattr(controller, "_last_run_config", {})
    assert run_config.get("prompt_source") == "pack"
    assert run_config.get("prompt_pack_id") == "pack-123"
