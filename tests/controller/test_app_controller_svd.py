from __future__ import annotations

from src.controller.app_controller import AppController


def test_get_supported_svd_models_returns_model_ids() -> None:
    controller = AppController.__new__(AppController)

    model_ids = controller.get_supported_svd_models()

    assert "stabilityai/stable-video-diffusion-img2vid" in model_ids
    assert "stabilityai/stable-video-diffusion-img2vid-xt" in model_ids


def test_on_webui_ready_triggers_deferred_autostart() -> None:
    class _JobController:
        def __init__(self) -> None:
            self.called = 0

        def trigger_deferred_autostart(self) -> None:
            self.called += 1

    controller = AppController.__new__(AppController)
    controller.pipeline_controller = type("PipelineControllerStub", (), {"_job_controller": _JobController()})()
    controller._append_log = lambda *_args, **_kwargs: None
    controller.current_operation_label = None
    controller.last_ui_action = None
    controller.refresh_resources_from_webui = lambda: None
    controller._spawn_tracked_thread = lambda *, target, name, purpose: target()

    controller.on_webui_ready()

    assert controller.pipeline_controller._job_controller.called == 1
