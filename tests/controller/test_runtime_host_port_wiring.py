from __future__ import annotations

from types import SimpleNamespace

import src.app_factory as app_factory
from src.controller.app_controller import AppController
from src.controller.pipeline_controller import PipelineController
from src.runtime_host import LocalRuntimeHostAdapter
from tests.helpers.job_service_di_test_helpers import make_stubbed_job_service


def test_pipeline_controller_wraps_injected_job_service_with_local_runtime_host() -> None:
    service = make_stubbed_job_service()

    controller = PipelineController(job_service=service)
    runtime_host = controller.get_runtime_host()

    assert isinstance(runtime_host, LocalRuntimeHostAdapter)
    assert runtime_host.job_service is service
    assert controller.get_job_service() is runtime_host


def test_app_controller_builds_local_runtime_host_by_default(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.controller.job_execution_controller.load_queue_snapshot",
        lambda *_, **__: None,
    )
    monkeypatch.setattr(
        "src.controller.job_execution_controller.save_queue_snapshot",
        lambda *_, **__: True,
    )

    controller = AppController(main_window=None, threaded=False)

    runtime_host = controller.job_service
    job_exec = controller.pipeline_controller.get_job_execution_controller()

    assert isinstance(runtime_host, LocalRuntimeHostAdapter)
    assert controller.pipeline_controller.get_runtime_host() is runtime_host
    assert runtime_host.queue is job_exec.get_queue()


def test_app_controller_wraps_injected_job_service_without_changing_shared_queue() -> None:
    service = make_stubbed_job_service()

    controller = AppController(main_window=None, threaded=False, job_service=service)
    runtime_host = controller.job_service
    job_exec = controller.pipeline_controller.get_job_execution_controller()

    assert isinstance(runtime_host, LocalRuntimeHostAdapter)
    assert runtime_host.job_service is service
    assert controller.pipeline_controller.get_runtime_host() is runtime_host
    assert runtime_host.queue is job_exec.get_queue()


def test_build_v2_app_launches_child_runtime_host_when_requested(monkeypatch) -> None:
    launched_runtime_host = SimpleNamespace(stop=lambda: None)
    root = SimpleNamespace(after=lambda delay, fn: None)

    class DummyController:
        def __init__(self, *args, runtime_host=None, **kwargs) -> None:
            self.runtime_host = runtime_host
            self.job_service = runtime_host
            self.pipeline_controller = SimpleNamespace()

        def attach_watchdog(self, diagnostics_service) -> None:
            self.diagnostics_service = diagnostics_service

        def get_gui_log_handler(self):
            return None

        def set_main_window(self, window) -> None:
            self.main_window = window

    class DummyWindow:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    monkeypatch.setattr(
        app_factory,
        "build_gui_kernel",
        lambda **kwargs: SimpleNamespace(
            pipeline_runner=object(),
            config_manager=object(),
            api_client=object(),
            structured_logger=object(),
            runtime_ports=object(),
            capabilities=object(),
        ),
    )
    monkeypatch.setattr(app_factory, "AppController", DummyController)
    monkeypatch.setattr(app_factory, "MainWindowV2", DummyWindow)
    monkeypatch.setattr(
        app_factory,
        "launch_child_runtime_host_client",
        lambda **kwargs: launched_runtime_host,
    )
    monkeypatch.setattr(app_factory, "get_job_history_path", lambda: "history.json")
    monkeypatch.setattr(
        "src.services.diagnostics_service_v2.DiagnosticsServiceV2",
        lambda *args, **kwargs: SimpleNamespace(),
    )

    _, _, controller, _ = app_factory.build_v2_app(
        root=root,
        launch_runtime_host=True,
    )

    assert controller.runtime_host is launched_runtime_host
    assert controller.job_service is launched_runtime_host