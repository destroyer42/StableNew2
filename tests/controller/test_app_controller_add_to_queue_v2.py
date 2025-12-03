from __future__ import annotations

from typing import Any

from src.controller.app_controller import AppController


class DummyAddToQueueHandler:
    def __init__(self) -> None:
        self.calls = 0

    def on_add_job_to_queue(self) -> None:
        self.calls += 1


def _build_controller(**kwargs: Any) -> AppController:
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


def test_on_add_job_to_queue_v2_uses_available_handler():
    controller = _build_controller()
    handler = DummyAddToQueueHandler()
    controller.on_add_job_to_queue = handler.on_add_job_to_queue  # type: ignore[attr-defined]

    controller.on_add_job_to_queue_v2()

    assert handler.calls == 1


def test_on_add_job_to_queue_v2_noop_without_handler():
    controller = _build_controller()

    controller.on_add_job_to_queue_v2()

    # No exception; method is a no-op when no handler exists
    assert True
