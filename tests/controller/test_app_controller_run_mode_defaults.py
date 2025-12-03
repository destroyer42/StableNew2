from types import SimpleNamespace

from src.controller.app_controller import AppController


class DummyPipelineController:
    def __init__(self):
        self.start_pipeline_called = 0

    def start_pipeline(self):
        self.start_pipeline_called += 1


def _build_controller(**kwargs):
    return AppController(
        main_window=None,
        pipeline_runner=None,
        api_client=None,
        structured_logger=None,
        webui_process_manager=None,
        config_manager=None,
        resource_service=None,
        job_service=None,
        **kwargs,
    )


def _attach_pipeline_state(controller, run_mode=None):
    state = SimpleNamespace(pipeline_state=SimpleNamespace(run_mode=run_mode))
    controller.app_state = state
    return state


def test_run_defaults_to_direct():
    controller = _build_controller()
    _attach_pipeline_state(controller)
    controller.start_run_v2()
    assert controller.app_state.pipeline_state.run_mode == "direct"


def test_run_now_defaults_to_queue():
    controller = _build_controller()
    _attach_pipeline_state(controller)
    controller.on_run_job_now_v2()
    assert controller.app_state.pipeline_state.run_mode == "queue"


def test_respects_existing_run_mode():
    controller = _build_controller()
    state = _attach_pipeline_state(controller)
    state.pipeline_state.run_mode = "queue"
    controller.start_run_v2()
    assert controller.app_state.pipeline_state.run_mode == "queue"
    state.pipeline_state.run_mode = "direct"
    controller.on_run_job_now_v2()
    assert controller.app_state.pipeline_state.run_mode == "direct"
