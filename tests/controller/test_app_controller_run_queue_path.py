from __future__ import annotations

from types import SimpleNamespace

from src.controller.app_controller import AppController
from tests.helpers.njr_factory import make_pipeline_njr


def test_run_txt2img_once_routes_supplied_intent_to_njr_queue() -> None:
    record = make_pipeline_njr(job_id="queued-from-run-button")
    captured: dict[str, object] = {}

    class _PipelineController:
        def get_preview_jobs_for_request(self, request):
            captured["request"] = request
            return [record]

        def submit_preview_jobs_to_queue(self, **kwargs):
            captured["submission"] = kwargs
            return 1

    controller = AppController.__new__(AppController)
    controller.pipeline_controller = _PipelineController()
    controller.pipeline_runner = SimpleNamespace(
        run_txt2img_once=lambda _config: (_ for _ in ()).throw(AssertionError("legacy runner used"))
    )
    controller._append_log = lambda _message: None
    controller._update_status = lambda _message: None

    result = controller.run_txt2img_once({"prompt": "a queued image"})

    assert result["success"] is True
    request = captured["request"]
    assert request.base_config == {"prompt": "a queued image"}
    submission = captured["submission"]
    assert submission["records"] == [record]
    assert submission["run_config"]["run_mode"] == "queue"


def test_run_txt2img_once_without_config_delegates_to_queue_run_event() -> None:
    controller = AppController.__new__(AppController)
    controller._append_log = lambda _message: None
    controller.on_run_now = lambda: "queued-event"

    assert controller.run_txt2img_once() == "queued-event"
