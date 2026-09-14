from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from src.controller.app_controller import AppController
from src.gui.app_state_v2 import AppStateV2
from src.queue.job_repository import JobRepository


class FakeJobService:
    def __init__(self, history_store=None) -> None:
        self.cancel_calls = 0
        self.stop_calls = 0
        self.history_store = history_store or type(
            "Store", (), {"list_jobs": lambda self, *args, **kwargs: []}
        )()

    def register_callback(self, *args, **kwargs):
        return None

    def cancel_current(self) -> None:
        self.cancel_calls += 1
        return None

    def stop(self) -> None:
        self.stop_calls += 1


class RecordingJobRepository(JobRepository):
    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.close_calls = 0
        self.post_close_write_attempts = 0
        self.events: list[str] = []
        self._closed_for_test = False

    def set_setting(self, key: str, value: object) -> None:
        if self._closed_for_test:
            self.post_close_write_attempts += 1
            raise AssertionError(f"post-close setting write: {key}")
        self.events.append(f"set_setting:{key}")
        super().set_setting(key, value)

    def close(self) -> None:
        self.close_calls += 1
        self.events.append("close")
        self._closed_for_test = True
        super().close()


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
def controller(tmp_path: Path) -> AppController:
    job_service = FakeJobService(history_store=JobRepository(tmp_path / "jobs.sqlite3"))
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


def test_shutdown_persists_final_queue_state_before_repository_close(tmp_path: Path) -> None:
    path = tmp_path / "jobs.sqlite3"
    repository = RecordingJobRepository(path)
    service = FakeJobService(history_store=repository)
    controller = AppController(None, threaded=False, job_service=service)
    controller.app_state = AppStateV2()
    job_execution = controller.pipeline_controller._job_controller

    job_execution.set_auto_run_enabled(False)
    job_execution.set_queue_paused(True)
    repository.set_setting("auto_run_enabled", True)
    repository.set_setting("queue_paused", False)
    repository.events.clear()
    persist_calls = 0
    original_persist = job_execution.persist_queue_state

    def record_persist() -> None:
        nonlocal persist_calls
        persist_calls += 1
        original_persist()

    job_execution.persist_queue_state = record_persist  # type: ignore[method-assign]

    controller.shutdown_app("queue-persistence-order")
    controller.shutdown_app("queue-persistence-order-repeat")

    assert persist_calls == 1
    assert repository.close_calls == 1
    assert repository.post_close_write_attempts == 0
    assert repository.events[-1] == "close"
    assert repository.events.index("set_setting:auto_run_enabled") < repository.events.index(
        "close"
    )
    assert repository.events.index("set_setting:queue_paused") < repository.events.index("close")
    assert service.stop_calls == 1

    with JobRepository(path) as reopened:
        assert reopened.get_setting("auto_run_enabled") is False
        assert reopened.get_setting("queue_paused") is True
