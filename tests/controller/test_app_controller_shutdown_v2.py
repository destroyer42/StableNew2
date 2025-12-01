from __future__ import annotations

import pytest

from src.controller.app_controller import AppController
from src.gui.app_state_v2 import AppStateV2


class FakeJobService:
    def __init__(self) -> None:
        self.cancel_calls = 0
        self.history_store = type("Store", (), {"list_jobs": lambda self, *args, **kwargs: []})()

    def register_callback(self, *args, **kwargs):
        return None

    def cancel_current(self) -> None:
        self.cancel_calls += 1
        return None


class FakeWebUIManager:
    def __init__(self) -> None:
        self.stop_calls = 0

    def stop_webui(self, *args, **kwargs) -> bool:
        self.stop_calls += 1
        return True


class FakeLearningController:
    def __init__(self) -> None:
        self.shutdown_calls = 0

    def shutdown(self) -> None:
        self.shutdown_calls += 1


@pytest.fixture
def controller() -> AppController:
    job_service = FakeJobService()
    webui = FakeWebUIManager()
    controller = AppController(None, threaded=False, job_service=job_service, webui_process_manager=webui)
    controller.app_state = AppStateV2()
    controller.learning_controller = FakeLearningController()
    return controller


def test_shutdown_app_invokes_subsystems(controller: AppController) -> None:
    controller.shutdown_app("test")
    assert isinstance(controller.job_service, FakeJobService)
    assert controller.job_service.cancel_calls == 1
    assert controller.webui_process_manager.stop_calls == 1
    learning_ctrl = controller.learning_controller
    assert learning_ctrl.shutdown_calls == 1

    controller.shutdown_app("again")
    assert controller.job_service.cancel_calls == 1
    assert controller.webui_process_manager.stop_calls == 1
    assert learning_ctrl.shutdown_calls == 1


def test_shutdown_app_handles_errors(controller: AppController) -> None:
    called = []

    def failing_cancel():
        called.append("cancel")
        raise RuntimeError("fail")

    controller.job_service.cancel_current = failing_cancel  # type: ignore[attr-defined]
    controller.shutdown_app("error")
    assert "cancel" in called
    assert controller.webui_process_manager.stop_calls == 1
