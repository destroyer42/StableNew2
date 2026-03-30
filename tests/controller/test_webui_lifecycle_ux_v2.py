from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.controller.app_controller import AppController
from src.runtime_host import RUNTIME_HOST_EVENT_DISCONNECTED, build_local_runtime_host
from tests.helpers.job_service_di_test_helpers import make_stubbed_job_service


class DummyLogWidget:
    def insert(self, *args, **kwargs):
        return None

    def see(self, *args, **kwargs):
        return None


class DummyStatusBar:
    def __init__(self):
        self.states: list[str] = []
        self.statuses: list[str] = []

    def update_webui_state(self, state: str):
        self.states.append(state)

    def update_status(self, text: str):
        self.statuses.append(text)


class DummyWindow:
    def __init__(self):
        self.status_bar_v2 = DummyStatusBar()
        self.bottom_zone = SimpleNamespace(log_text=DummyLogWidget(), status_label=None)
        self.controller = None

    def connect_controller(self, controller):
        self.controller = controller

    def after(self, _delay, callback):
        callback()

    def update_pack_list(self, _names):
        return None


class FakePipelineRunner:
    def run(self, *_args, **_kwargs):
        return


class FakeWebUIManager:
    def __init__(self, ensure=True, health=True):
        self.ensure_result = ensure
        self.health_result = health
        self.ensure_calls = 0
        self.health_calls = 0

    def ensure_running(self):
        self.ensure_calls += 1
        return self.ensure_result

    def check_health(self):
        self.health_calls += 1
        return self.health_result


@pytest.fixture(autouse=True)
def skip_attach(monkeypatch):
    monkeypatch.setattr(AppController, "_attach_to_gui", lambda self: None)
    yield


def test_on_launch_webui_updates_state():
    window = DummyWindow()
    fake_manager = FakeWebUIManager(ensure=True)
    controller = AppController(
        window,
        pipeline_runner=FakePipelineRunner(),
        threaded=False,
        webui_process_manager=fake_manager,
    )

    controller.on_launch_webui_clicked()

    assert fake_manager.ensure_calls == 1
    assert window.status_bar_v2.states[-1] == "connected"


def test_on_launch_webui_handles_failure():
    window = DummyWindow()
    fake_manager = FakeWebUIManager(ensure=False)
    controller = AppController(
        window,
        pipeline_runner=FakePipelineRunner(),
        threaded=False,
        webui_process_manager=fake_manager,
    )

    controller.on_launch_webui_clicked()

    assert window.status_bar_v2.states[-1] == "error"


def test_on_retry_webui_updates_state():
    window = DummyWindow()
    fake_manager = FakeWebUIManager(health=True)
    controller = AppController(
        window,
        pipeline_runner=FakePipelineRunner(),
        threaded=False,
        webui_process_manager=fake_manager,
    )

    controller.on_retry_webui_clicked()

    assert fake_manager.health_calls == 1
    assert window.status_bar_v2.states[-1] == "connected"


def test_on_launch_webui_uses_runtime_host_when_remote():
    window = DummyWindow()
    runtime_host = build_local_runtime_host(make_stubbed_job_service())
    runtime_host.describe_protocol = lambda: {"transport": "local-child"}  # type: ignore[method-assign]
    runtime_host.ensure_webui_ready = (  # type: ignore[attr-defined]
        lambda *, autostart=True: {"state": "ready", "pid": 321, "autostart": autostart}
    )
    controller = AppController(
        window,
        pipeline_runner=FakePipelineRunner(),
        threaded=False,
        runtime_host=runtime_host,
    )

    controller.on_launch_webui_clicked()

    assert window.status_bar_v2.states[-1] == "connected"


def test_on_retry_webui_uses_runtime_host_when_remote():
    window = DummyWindow()
    runtime_host = build_local_runtime_host(make_stubbed_job_service())
    runtime_host.describe_protocol = lambda: {"transport": "local-child"}  # type: ignore[method-assign]
    runtime_host.retry_webui_connection = lambda: {"state": "ready", "pid": 321}  # type: ignore[attr-defined]
    controller = AppController(
        window,
        pipeline_runner=FakePipelineRunner(),
        threaded=False,
        runtime_host=runtime_host,
    )

    controller.on_retry_webui_clicked()

    assert window.status_bar_v2.states[-1] == "connected"


def test_runtime_host_disconnect_updates_status_and_webui_state():
    window = DummyWindow()
    runtime_host = build_local_runtime_host(make_stubbed_job_service())
    runtime_host.describe_protocol = lambda: {"transport": "local-child"}  # type: ignore[method-assign]
    controller = AppController(
        window,
        pipeline_runner=FakePipelineRunner(),
        threaded=False,
        runtime_host=runtime_host,
    )

    runtime_host.job_service._emit(  # type: ignore[attr-defined]
        RUNTIME_HOST_EVENT_DISCONNECTED,
        {"transport": "local-child", "error": "pipe closed"},
    )

    assert window.status_bar_v2.states[-1] == "error"
    assert "pipe closed" in window.status_bar_v2.statuses[-1]
    assert controller._pending_status_text.endswith("pipe closed")
