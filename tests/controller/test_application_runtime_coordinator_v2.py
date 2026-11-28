from __future__ import annotations

import threading
from types import SimpleNamespace

from src.controller.app_controller_services.application_runtime_coordinator import (
    ApplicationRuntimeCoordinator,
)


class _JobControllerStub:
    def __init__(self) -> None:
        self.auto_run_enabled = True
        self.is_queue_paused = False
        self.trigger_calls = 0

    def trigger_deferred_autostart(self) -> None:
        self.trigger_calls += 1


class _WebUIStub:
    def __init__(self, ready: bool) -> None:
        self._ready = ready

    def is_webui_ready_strict(self) -> bool:
        return self._ready


def test_application_runtime_coordinator_waits_for_gui_ready() -> None:
    job_controller = _JobControllerStub()
    coordinator = ApplicationRuntimeCoordinator(
        job_controller=job_controller,
        webui_connection_controller=_WebUIStub(ready=True),
        spawn=lambda work: work(),
    )

    coordinator.on_webui_ready()
    assert job_controller.trigger_calls == 0

    coordinator.on_gui_ready()
    assert job_controller.trigger_calls == 1


def test_application_runtime_coordinator_syncs_queue_flags() -> None:
    job_controller = _JobControllerStub()
    app_state = SimpleNamespace(
        auto_run_queue=None,
        is_queue_paused=None,
        set_auto_run_queue=lambda value: setattr(app_state, "auto_run_queue", value),
        set_is_queue_paused=lambda value: setattr(app_state, "is_queue_paused", value),
    )
    job_service = SimpleNamespace(auto_run_enabled=False)
    coordinator = ApplicationRuntimeCoordinator(
        job_controller=job_controller,
        webui_connection_controller=_WebUIStub(ready=False),
    )

    coordinator.sync_queue_state(app_state=app_state, job_service=job_service)

    assert app_state.auto_run_queue is True
    assert app_state.is_queue_paused is False
    assert job_service.auto_run_enabled is True


def test_application_runtime_coordinator_defers_until_webui_ready_after_gui() -> None:
    job_controller = _JobControllerStub()
    webui = _WebUIStub(ready=False)
    coordinator = ApplicationRuntimeCoordinator(
        job_controller=job_controller,
        webui_connection_controller=webui,
        spawn=lambda work: work(),
    )

    coordinator.on_gui_ready()
    assert job_controller.trigger_calls == 0

    webui._ready = True
    coordinator.on_webui_ready()

    assert job_controller.trigger_calls == 1


def test_the_gui_ready_check_runs_off_the_calling_thread() -> None:
    """STARTUP-STALL: the strict readiness probe does network I/O, so never on the Tk thread."""

    checked_on: list[int] = []
    done = threading.Event()

    class _Probe:
        def is_webui_ready_strict(self) -> bool:
            checked_on.append(threading.get_ident())
            return True

    class _Job(_JobControllerStub):
        def trigger_deferred_autostart(self) -> None:
            super().trigger_deferred_autostart()
            done.set()

    job_controller = _Job()
    coordinator = ApplicationRuntimeCoordinator(
        job_controller=job_controller, webui_connection_controller=_Probe()
    )

    coordinator.on_gui_ready()

    assert done.wait(5)
    assert checked_on and checked_on != [threading.get_ident()]
    assert job_controller.trigger_calls == 1
