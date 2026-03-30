from __future__ import annotations

import pytest
from unittest.mock import patch

from src.controller.app_controller import AppController
from src.gui.app_state_v2 import AppStateV2
from src.runtime_host import build_local_runtime_host
from tests.helpers.job_service_di_test_helpers import make_stubbed_job_service


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
    controller = AppController(
        None, threaded=False, job_service=job_service, webui_process_manager=webui
    )
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


def test_shutdown_app_uses_daemon_watchdog_thread(controller: AppController) -> None:
    controller._shutdown_watchdog = lambda: None  # type: ignore[method-assign]

    controller.shutdown_app("watchdog-test")

    watchdog = controller._shutdown_watchdog_thread
    assert watchdog is not None
    assert watchdog.daemon is True


def test_shutdown_app_waits_for_watchdog_before_closing_loggers(controller: AppController) -> None:
    import threading

    started = threading.Event()
    tick = threading.Event()

    def fake_watchdog() -> None:
        started.set()
        while not controller._shutdown_completed:
            tick.wait(0.001)

    def assert_close_order() -> None:
        assert started.wait(timeout=1.0)
        watchdog = controller._shutdown_watchdog_thread
        assert watchdog is not None
        assert not watchdog.is_alive()

    controller._shutdown_watchdog = fake_watchdog  # type: ignore[method-assign]

    with patch("src.controller.app_controller.close_all_structured_loggers", side_effect=assert_close_order):
        controller.shutdown_app("watchdog-order")


def test_shutdown_webui_uses_global_manager_fallback(controller: AppController) -> None:
    fallback = FakeWebUIManager()
    controller.webui_process_manager = None

    with patch("src.controller.app_controller.get_global_webui_process_manager", return_value=fallback):
        controller._shutdown_webui()

    assert controller.webui_process_manager is fallback
    assert fallback.stop_calls == 1


def test_shutdown_app_stops_remote_runtime_host() -> None:
    runtime_host = build_local_runtime_host(make_stubbed_job_service())
    runtime_host.describe_protocol = lambda: {"transport": "local-child"}  # type: ignore[method-assign]
    stop_calls: list[str] = []
    runtime_host.stop = lambda: stop_calls.append("stop")  # type: ignore[attr-defined]

    controller = AppController(
        None,
        threaded=False,
        runtime_host=runtime_host,
        webui_process_manager=FakeWebUIManager(),
    )
    controller.app_state = AppStateV2()
    controller.learning_controller = FakeLearningController()

    controller.shutdown_app("remote-host")

    assert stop_calls == ["stop"]
