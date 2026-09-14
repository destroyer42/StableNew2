"""Ownership-scoped WebUI/ComfyUI process cleanup tests."""

from __future__ import annotations

import sys
import time
from unittest.mock import Mock

import pytest

from src.api.webui_process_manager import (
    WebUIProcessConfig,
    WebUIProcessManager,
    WebUIStartupError,
    kill_orphaned_webui_processes_blocking_port,
)
from src.utils.process_container_v2 import NullProcessContainer
from src.video.comfy_process_manager import ComfyProcessConfig, ComfyProcessManager
from tests.helpers.webui_mocks import DummyProcess


def _manager(monkeypatch, *, working_dir=None, base_url=None) -> WebUIProcessManager:
    monkeypatch.setattr(
        "src.api.webui_process_manager.build_process_container",
        lambda job_id, config: NullProcessContainer(job_id, config),
    )
    manager = WebUIProcessManager(
        WebUIProcessConfig(
            command=[sys.executable, "-c", "import time; time.sleep(60)"],
            working_dir=working_dir,
            base_url=base_url,
        )
    )
    manager._start_orphan_monitor = Mock()
    return manager


@pytest.mark.parametrize("working_dir", [None, r"C:\stable-diffusion-webui"])
def test_occupied_external_endpoint_is_never_killed(monkeypatch, working_dir) -> None:
    manager = _manager(
        monkeypatch,
        working_dir=working_dir,
        base_url="http://127.0.0.1:7860",
    )
    monkeypatch.setattr(
        "src.utils.single_instance.SingleInstanceLock.is_gui_running", lambda: True
    )
    monkeypatch.setattr(manager, "_configured_endpoint_is_occupied", lambda: True)
    popen = Mock()
    monkeypatch.setattr("src.api.webui_process_manager.subprocess.Popen", popen)

    with pytest.raises(WebUIStartupError, match="will not kill or adopt"):
        manager.start()

    popen.assert_not_called()
    assert manager.owns_process is False


def test_heuristic_port_cleanup_is_non_destructive(monkeypatch) -> None:
    process_iter = Mock(side_effect=AssertionError("machine-wide scan is forbidden"))
    fake_psutil = Mock(process_iter=process_iter)
    monkeypatch.setitem(sys.modules, "psutil", fake_psutil)

    assert kill_orphaned_webui_processes_blocking_port(
        port=7860, working_dir=r"C:\stable-diffusion-webui"
    ) == []
    process_iter.assert_not_called()


def test_shutdown_without_owned_process_performs_zero_termination(monkeypatch) -> None:
    manager = _manager(monkeypatch)
    external = DummyProcess()
    external.terminate = Mock()
    external.kill = Mock()
    manager._process = external
    manager._pid = external.pid
    manager._owns_process = False
    tree_kill = Mock()
    monkeypatch.setattr(manager, "_kill_process_tree", tree_kill)

    assert manager.stop_webui(grace_seconds=0.01) is True

    external.terminate.assert_not_called()
    external.kill.assert_not_called()
    tree_kill.assert_not_called()


def test_manager_owned_root_and_only_owned_descendants_are_terminated(monkeypatch) -> None:
    manager = _manager(monkeypatch, working_dir=r"C:\stable-diffusion-webui")
    root = DummyProcess(pid=100)
    root.terminate = Mock(side_effect=root.terminate)
    owned_child = Mock(pid=101)
    unrelated_same_directory_process = Mock(pid=102)
    monkeypatch.setattr("src.api.webui_process_manager.subprocess.Popen", Mock(return_value=root))
    monkeypatch.setattr(
        "src.utils.single_instance.SingleInstanceLock.is_gui_running", lambda: True
    )
    manager.start()
    monkeypatch.setattr(manager, "_owned_descendants", lambda pid: [owned_child])

    assert manager.stop_webui(grace_seconds=0.01) is True

    root.terminate.assert_called_once()
    owned_child.kill.assert_called_once()
    unrelated_same_directory_process.kill.assert_not_called()


def test_process_tree_kill_requires_matching_launch_session(monkeypatch) -> None:
    manager = _manager(monkeypatch)
    manager._process = DummyProcess(pid=200)
    manager._pid = 200
    manager._owns_process = False
    descendants = Mock()
    monkeypatch.setattr(manager, "_owned_descendants", descendants)

    manager._kill_process_tree(200)
    manager._kill_process_tree(201)

    descendants.assert_not_called()


def test_restart_refuses_unmanaged_external_process(monkeypatch) -> None:
    manager = _manager(monkeypatch)
    manager._process = DummyProcess(pid=300)
    manager._pid = 300
    stop = Mock()
    start = Mock()
    monkeypatch.setattr(manager, "stop_webui", stop)
    monkeypatch.setattr(manager, "start", start)

    assert manager.restart_webui(wait_ready=False) is False
    stop.assert_not_called()
    start.assert_not_called()


def test_orphan_cleanup_targets_only_owned_manager_process(monkeypatch) -> None:
    manager = _manager(monkeypatch)
    manager._process = DummyProcess(pid=400)
    manager._pid = 400
    kill_tree = Mock()
    monkeypatch.setattr(manager, "_kill_process_tree", kill_tree)

    manager._kill_all_webui_processes()
    kill_tree.assert_not_called()

    manager._owns_process = True
    manager._kill_all_webui_processes()
    kill_tree.assert_called_once_with(400)


def test_emergency_cleanup_is_ownership_scoped(monkeypatch) -> None:
    import src.main as main_module

    unmanaged_webui = Mock(owns_process=False)
    unmanaged_comfy = Mock(owns_process=False)
    monkeypatch.setattr(main_module, "_webui_manager_global", unmanaged_webui)
    monkeypatch.setattr(main_module, "_comfy_manager_global", unmanaged_comfy)

    main_module._emergency_webui_cleanup()
    main_module._emergency_comfy_cleanup()

    unmanaged_webui.stop_webui.assert_not_called()
    unmanaged_comfy.stop.assert_not_called()


def test_emergency_cleanup_stops_owned_managers(monkeypatch) -> None:
    import src.main as main_module

    owned_webui = Mock(owns_process=True)
    owned_comfy = Mock(owns_process=True)
    monkeypatch.setattr(main_module, "_webui_manager_global", owned_webui)
    monkeypatch.setattr(main_module, "_comfy_manager_global", owned_comfy)

    main_module._emergency_webui_cleanup()
    main_module._emergency_comfy_cleanup()

    owned_webui.stop_webui.assert_called_once_with(grace_seconds=1.0)
    owned_comfy.stop.assert_called_once_with(grace_seconds=1.0)


def test_emergency_registration_is_isolated_and_idempotent(monkeypatch) -> None:
    import src.main as main_module

    callbacks = []
    window = Mock()
    window.webui_process_manager = Mock(owns_process=False)
    window.comfy_process_manager = Mock(owns_process=False)
    monkeypatch.setattr(main_module, "_emergency_cleanup_registered", False)
    monkeypatch.setattr(main_module, "_webui_manager_global", None)
    monkeypatch.setattr(main_module, "_comfy_manager_global", None)
    register = Mock(side_effect=callbacks.append)
    monkeypatch.setattr(main_module.atexit, "register", register)

    main_module._register_emergency_cleanup(window)
    main_module._register_emergency_cleanup(window)

    assert callbacks == [
        main_module._emergency_webui_cleanup,
        main_module._emergency_comfy_cleanup,
    ]
    assert register.call_count == 2


def test_external_comfy_process_survives_shutdown(monkeypatch) -> None:
    manager = ComfyProcessManager(ComfyProcessConfig(command=["external-comfy"]))
    external = DummyProcess(pid=500)
    external.terminate = Mock()
    external.kill = Mock()
    manager._process = external

    manager.stop(grace_seconds=0.01)

    external.terminate.assert_not_called()
    external.kill.assert_not_called()


def test_owned_disposable_process_tree_is_stopped(monkeypatch, tmp_path) -> None:
    psutil = pytest.importorskip("psutil")
    child_pid_file = tmp_path / "child.pid"
    code = (
        "import pathlib, subprocess, sys, time; "
        "p=subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
        f"pathlib.Path({str(child_pid_file)!r}).write_text(str(p.pid)); "
        "time.sleep(60)"
    )
    manager = _manager(monkeypatch, working_dir=str(tmp_path))
    manager._config.command = [sys.executable, "-c", code]
    monkeypatch.setattr(
        "src.utils.single_instance.SingleInstanceLock.is_gui_running", lambda: True
    )
    manager.start()
    deadline = time.monotonic() + 5.0
    while not child_pid_file.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert child_pid_file.exists()
    child_pid = int(child_pid_file.read_text())

    try:
        assert manager.owns_process is True
        assert psutil.pid_exists(child_pid)
        assert manager.stop_webui(grace_seconds=0.2) is True
        deadline = time.monotonic() + 3.0
        while psutil.pid_exists(child_pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not psutil.pid_exists(child_pid)
    finally:
        for pid in (child_pid, manager.pid):
            if pid and psutil.pid_exists(pid):
                psutil.Process(pid).kill()
