"""PR-RUNTIME-WEBUI-LIFECYCLE-130: startup, connection, recovery and resources observe ONE manager.

Real ``WebUIProcessManager`` / ``WebUIConnectionController`` / ``AppController`` / ``AppStateV2`` objects with
a fake process, fake readiness probes and a scripted resource service. Nothing is spawned or contacted and no
test waits on a clock.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest import mock

import pytest

from src import main
from src.api import healthcheck
from src.api import webui_process_manager as wpm
from src.api.webui_process_manager import WebUIProcessConfig, WebUIProcessManager
from src.controller.app_controller import AppController
from src.controller.webui_connection_controller import (
    WebUIConnectionController,
    WebUIConnectionState,
)
from src.utils.config import ConfigManager
from tests.helpers.job_service_di_test_helpers import make_stubbed_job_service
from tests.helpers.webui_mocks import DummyProcess

URL = "http://127.0.0.1:7871"
RESOURCES = {
    "models": ["forge-model.safetensors"],
    "vaes": ["vae.safetensors"],
    "samplers": ["Euler a"],
    "schedulers": ["Karras"],
    "upscalers": ["R-ESRGAN 4x+"],
    "hypernetworks": [],
    "embeddings": [],
    "adetailer_models": ["face_yolov8n.pt"],
    "adetailer_detectors": [],
}
EMPTY = {key: [] for key in RESOURCES}


@pytest.fixture(autouse=True)
def _clean_lifecycle_state(monkeypatch):
    wpm.clear_global_webui_process_manager()
    healthcheck.clear_readiness_failure_state()
    monkeypatch.setattr(
        "src.utils.single_instance.SingleInstanceLock.is_gui_running", staticmethod(lambda *a, **k: True)
    )
    monkeypatch.setattr(wpm, "build_process_container", mock.Mock(return_value=mock.Mock()))
    monkeypatch.setattr(WebUIProcessManager, "_start_orphan_monitor", mock.Mock())
    monkeypatch.setattr(WebUIProcessManager, "_configured_endpoint_is_occupied", lambda self: False)
    yield
    wpm.clear_global_webui_process_manager()
    healthcheck.clear_readiness_failure_state()


def _process_config(**extra) -> WebUIProcessConfig:
    return WebUIProcessConfig(
        command=["python", "webui.py"],
        base_url=URL,
        runtime_identity="forge_webui",
        autostart_enabled=True,
        startup_timeout_seconds=extra.pop("startup_timeout_seconds", 0.5),
        **extra,
    )


def _started_manager(monkeypatch, *, pid: int = 4242) -> tuple[WebUIProcessManager, DummyProcess]:
    process = DummyProcess(pid=pid)
    monkeypatch.setattr("subprocess.Popen", mock.Mock(return_value=process))
    manager = WebUIProcessManager(_process_config())
    manager.start()
    return manager, process


class _Registry:
    """Runs spawned worker targets inline so the bootstrap worker is deterministic."""

    def spawn(self, *, target, args=(), kwargs=None, **_options):
        target(*args, **(kwargs or {}))
        return mock.Mock()


class _Panel:
    def __init__(self) -> None:
        self.states: list[WebUIConnectionState] = []

    def set_launch_callback(self, _cb) -> None: ...

    def set_retry_callback(self, _cb) -> None: ...

    def set_webui_state(self, state) -> None:
        self.states.append(state)


class _Window:
    def __init__(self, app_controller) -> None:
        self.app_controller = app_controller
        self.webui_process_manager = None
        self.status_bar_v2 = SimpleNamespace(webui_panel=_Panel())
        self.sidebar_panel_v2 = SimpleNamespace(refresh_base_generation_from_webui=mock.Mock())
        self.periodic: list = []

    def after(self, _delay, callback) -> None:
        self.periodic.append(callback)

    def run_in_main_thread(self, fn) -> None:
        fn()


def _bootstrap_config(**extra) -> dict:
    return {
        "webui_base_url": URL,
        "webui_autostart_enabled": True,
        "process_config": _process_config(**extra),
        "webui_startup_timeout_seconds": 0.5,
    }


# --- A: startup / bootstrap ----------------------------------------------------------------------


def _run_async_bootstrap(monkeypatch, window, config, wait) -> None:
    monkeypatch.setattr("src.utils.thread_registry.get_thread_registry", lambda: _Registry())
    monkeypatch.setattr(main, "_load_webui_config", lambda: config)
    monkeypatch.setattr(main, "wait_for_webui_ready", wait)
    root = SimpleNamespace(after=lambda _delay, fn: fn())
    main._async_bootstrap_webui(root, mock.Mock(), window)


def test_bootstrap_delivers_the_manager_even_when_readiness_never_arrives(monkeypatch):
    monkeypatch.setattr("subprocess.Popen", mock.Mock(return_value=DummyProcess(pid=555)))
    window = _Window(SimpleNamespace(_api_client=None, webui_connection_controller=None))
    timeout = mock.Mock(side_effect=healthcheck.WebUIHealthCheckTimeout("never ready"))

    _run_async_bootstrap(monkeypatch, window, _bootstrap_config(), timeout)

    manager = wpm.get_global_webui_process_manager()
    assert manager is not None and manager.owns_process  # slow/never-ready startup keeps truthful ownership
    assert window.webui_process_manager is manager  # ... and it is visible to the window/controller


def test_bootstrap_delivers_the_manager_before_it_waits_for_readiness(monkeypatch):
    monkeypatch.setattr("subprocess.Popen", mock.Mock(return_value=DummyProcess(pid=556)))
    window = _Window(SimpleNamespace(_api_client=None, webui_connection_controller=None))
    seen_at_probe = []

    def wait(url, timeout, poll_interval):
        seen_at_probe.append(window.webui_process_manager)
        return True

    _run_async_bootstrap(monkeypatch, window, _bootstrap_config(), wait)

    assert seen_at_probe and seen_at_probe[0] is not None


def test_bootstrap_reports_an_early_exit_with_pid_exit_code_and_output_tail(monkeypatch, caplog):
    process = DummyProcess(pid=777)
    monkeypatch.setattr("subprocess.Popen", mock.Mock(return_value=process))
    window = _Window(SimpleNamespace(_api_client=None, webui_connection_controller=None))

    def wait(url, timeout, poll_interval):
        manager = wpm.get_global_webui_process_manager()
        manager._stderr_tail.append("RuntimeError: CUDA out of memory")
        process._returncode = 2
        raise healthcheck.WebUIHealthCheckTimeout("not ready")

    with caplog.at_level(logging.WARNING):
        _run_async_bootstrap(monkeypatch, window, _bootstrap_config(), wait)

    text = caplog.text
    assert "777" in text and "exit code 2" in text and "forge_webui" in text
    assert "CUDA out of memory" in text


def test_bootstrap_marks_the_manager_ready_when_the_probe_succeeds(monkeypatch):
    monkeypatch.setattr("subprocess.Popen", mock.Mock(return_value=DummyProcess(pid=558)))
    window = _Window(SimpleNamespace(_api_client=None, webui_connection_controller=None))

    _run_async_bootstrap(monkeypatch, window, _bootstrap_config(), lambda *a, **k: True)

    assert wpm.get_global_webui_process_manager().ready_epoch == 1


# --- B: one manager through connection ----------------------------------------------------------


def _controller_with_failing_fast_probe(monkeypatch, results):
    outcomes = list(results)

    def fake_wait(url, timeout=0, poll_interval=0):
        return outcomes.pop(0)

    monkeypatch.setattr("src.controller.webui_connection_controller.wait_for_webui_ready", fake_wait)
    monkeypatch.setattr(
        "src.controller.webui_connection_controller.app_config.get_webui_autostart_enabled", lambda: True
    )
    monkeypatch.setattr("src.controller.webui_connection_controller.time.sleep", lambda *a, **k: None)
    monkeypatch.setattr("src.api.healthcheck.find_webui_port", lambda *a, **k: None)
    constructed = mock.Mock()
    monkeypatch.setattr("src.controller.webui_connection_controller.WebUIProcessManager", constructed)
    monkeypatch.setattr(
        "src.controller.webui_connection_controller.build_default_webui_process_config",
        lambda: _process_config(),
    )
    return WebUIConnectionController(base_url_provider=lambda: URL), constructed


def test_ensure_connected_reuses_the_active_owned_manager_instead_of_constructing_a_second(monkeypatch):
    owner, process = _started_manager(monkeypatch)
    controller, constructed = _controller_with_failing_fast_probe(monkeypatch, [False, True])

    state = controller.ensure_connected(autostart=True)

    assert state is WebUIConnectionState.READY
    constructed.assert_not_called()
    assert wpm.get_global_webui_process_manager() is owner
    assert owner.process is process


def test_ensure_connected_uses_an_attached_manager_even_before_it_owns_a_process(monkeypatch):
    attached = WebUIProcessManager(_process_config())
    attached.start = mock.Mock()
    controller, constructed = _controller_with_failing_fast_probe(monkeypatch, [False, True])
    controller.attach_process_manager(attached)

    assert controller.ensure_connected(autostart=True) is WebUIConnectionState.READY

    constructed.assert_not_called()
    attached.start.assert_called_once()


def test_ensure_connected_still_builds_one_manager_when_none_exists(monkeypatch):
    controller, constructed = _controller_with_failing_fast_probe(monkeypatch, [False, True])

    assert controller.ensure_connected(autostart=True) is WebUIConnectionState.READY

    constructed.assert_called_once()


# --- C/D: a recovery is observed by the connection controller and AppController ------------------


class _ScriptedResourceService:
    """``refresh_all`` returns scripted payloads: service down (all-empty) first, then populated."""

    def __init__(self, *payloads) -> None:
        self._payloads = list(payloads)
        self.calls = 0

    def refresh_all(self, *_a, **_k):
        self.calls += 1
        payload = self._payloads.pop(0) if len(self._payloads) > 1 else self._payloads[0]
        if isinstance(payload, Exception):
            raise payload
        return {key: list(value) for key, value in payload.items()}


def _app(tmp_path, resource_service) -> AppController:
    client = SimpleNamespace(
        set_options_write_enabled=lambda *_a, **_k: None,
        clear_startup_probe_grace=mock.Mock(),
        clear_runtime_failure_state=mock.Mock(),
    )
    return AppController(
        main_window=None,
        pipeline_runner=None,
        structured_logger=None,
        webui_process_manager=None,
        config_manager=ConfigManager(presets_dir=tmp_path / "presets", packs_dir=tmp_path / "packs"),
        job_service=make_stubbed_job_service(),
        api_client=client,
        resource_service=resource_service,
        threaded=False,
    )


def _restart_ready(manager: WebUIProcessManager) -> bool:
    api = mock.Mock()
    with (
        mock.patch.object(manager, "stop_webui"),
        mock.patch.object(manager, "start"),
        mock.patch.object(WebUIProcessManager, "owns_process", mock.PropertyMock(return_value=True)),
        mock.patch("src.api.webui_api.WebUIAPI", return_value=api),
        mock.patch("src.api.webui_process_manager.time.sleep"),
    ):
        return manager.restart_webui(wait_ready=True, max_attempts=1)


def test_a_manager_restart_is_observed_by_the_connection_controller_as_one_ready_event(
    monkeypatch, tmp_path
):
    app = _app(tmp_path, _ScriptedResourceService(RESOURCES))
    controller = app.webui_connection_controller
    ready = mock.Mock()
    controller.register_on_ready(ready)
    manager = WebUIProcessManager(_process_config())
    window = _Window(app)
    main._update_window_webui_manager(window, manager)

    assert _restart_ready(manager)

    ready.assert_called_once()
    assert controller.get_state() is WebUIConnectionState.READY


def test_after_a_restart_the_resource_lists_reach_the_app_state_and_dropdown_listeners(
    monkeypatch, tmp_path
):
    service = _ScriptedResourceService(EMPTY, RESOURCES)
    app = _app(tmp_path, service)
    listener = mock.Mock()
    app.app_state.subscribe("resources", listener)
    manager = WebUIProcessManager(_process_config())
    main._update_window_webui_manager(_Window(app), manager)
    app.refresh_resources_from_webui()  # endpoint unavailable: the refresh yields empty lists
    assert app.app_state.resources["models"] == []

    assert _restart_ready(manager)  # unavailable -> restart -> TRUE-READY

    assert service.calls == 2  # exactly one refresh was caused by the recovery
    assert app.app_state.resources["models"] == ["forge-model.safetensors"]
    assert app.app_state.resources["vaes"] == ["vae.safetensors"]
    assert app.app_state.resources["samplers"] == ["Euler a"]
    assert app.app_state.resources["schedulers"] == ["Karras"]
    assert app.app_state.resources["upscalers"] == ["R-ESRGAN 4x+"]
    assert app.app_state.resources["adetailer_models"] == ["face_yolov8n.pt"]
    listener.assert_called()


def test_a_failed_refresh_during_downtime_never_becomes_the_final_state(monkeypatch, tmp_path):
    service = _ScriptedResourceService(RuntimeError("connection refused"), RESOURCES)
    app = _app(tmp_path, service)
    manager = WebUIProcessManager(_process_config())
    main._update_window_webui_manager(_Window(app), manager)
    app.refresh_resources_from_webui()  # raises inside the service; logged, nothing published

    assert _restart_ready(manager)

    assert app.app_state.resources["models"] == ["forge-model.safetensors"]


def test_periodic_status_wiring_does_not_add_a_second_refresh_for_the_same_recovery(monkeypatch, tmp_path):
    service = _ScriptedResourceService(RESOURCES)
    app = _app(tmp_path, service)
    manager = WebUIProcessManager(_process_config())
    window = _Window(app)
    main._update_window_webui_manager(window, manager)

    assert _restart_ready(manager)
    after_recovery = service.calls
    for tick in list(window.periodic):  # the 1 s kick-off and any queued periodic checks
        tick()

    assert after_recovery == 1
    assert service.calls == 1
    assert window.sidebar_panel_v2.refresh_base_generation_from_webui.call_count >= 1


def test_each_new_readiness_epoch_refreshes_again(monkeypatch, tmp_path):
    service = _ScriptedResourceService(RESOURCES)
    app = _app(tmp_path, service)
    manager = WebUIProcessManager(_process_config())
    main._update_window_webui_manager(_Window(app), manager)

    assert _restart_ready(manager)
    assert _restart_ready(manager)

    assert service.calls == 2


def test_proven_ready_clears_the_shared_client_failure_state_so_the_refresh_is_not_suppressed(
    monkeypatch, tmp_path
):
    app = _app(tmp_path, _ScriptedResourceService(RESOURCES))
    manager = WebUIProcessManager(_process_config())
    main._update_window_webui_manager(_Window(app), manager)

    assert _restart_ready(manager)

    app._api_client.clear_runtime_failure_state.assert_called()


def test_strict_readiness_follows_the_restarted_process_not_the_dead_one(monkeypatch, tmp_path):
    controller = WebUIConnectionController(base_url_provider=lambda: URL)
    monkeypatch.setattr(
        "src.controller.webui_connection_controller.psutil.pid_exists", lambda pid: pid == 1002
    )
    manager, process = _started_manager(monkeypatch, pid=1001)
    controller.attach_process_manager(manager)
    manager.mark_ready(source="startup")
    process._returncode = 0  # the old process dies during restart; the controller must not detach
    new_process = DummyProcess(pid=1002)
    manager._process = new_process
    manager._pid = new_process.pid

    manager.mark_ready(source="restart")

    assert controller.is_process_alive() is True
    assert controller._process_manager is manager


# --- F: a runtime switch is configuration only; the running runtime is never touched -----------------


def test_saving_a_runtime_switch_does_not_kill_adopt_or_hot_switch_the_running_manager(
    monkeypatch, tmp_path
):
    from src.api.webui_runtime_identity import (
        A1111_DEFAULT_BASE_URL,
        resolve_configured_webui_runtime_identity,
    )

    monkeypatch.delenv("STABLENEW_WEBUI_RUNTIME_IDENTITY", raising=False)
    monkeypatch.delenv("STABLENEW_WEBUI_BASE_URL", raising=False)
    manager, process = _started_manager(monkeypatch, pid=2468)
    app = _app(tmp_path, _ScriptedResourceService(RESOURCES))
    app.webui_process_manager = manager

    app.on_settings_saved(
        {"webui_runtime_identity": "a1111_webui", "webui_base_url": A1111_DEFAULT_BASE_URL}
    )

    settings = app._config_manager.load_settings()
    assert resolve_configured_webui_runtime_identity(settings) == "a1111_webui"  # persisted for the next start
    assert manager.owns_process and manager.process is process and process.poll() is None
    assert manager.runtime_identity == "forge_webui"  # the running runtime did not hot-switch
    assert wpm.get_global_webui_process_manager() is manager
    assert manager.ready_epoch == 0  # saving settings is not a readiness event
