from __future__ import annotations

import io
from pathlib import Path
from unittest import mock

import pytest

from src.utils.config import ConfigManager
from src.video.comfy_healthcheck import ComfyHealthCheckTimeout
from src.video.comfy_process_manager import (
    ComfyProcessConfig,
    ComfyProcessManager,
    ComfyStartupError,
    build_default_comfy_process_config,
)


class _DummyProcess:
    def __init__(self, pid: int = 54321, stdout_text: str = "", stderr_text: str = "") -> None:
        self.pid = pid
        self._returncode = None
        self.stdout = io.StringIO(stdout_text)
        self.stderr = io.StringIO(stderr_text)

    def poll(self):
        return self._returncode

    def terminate(self):
        self._returncode = 0

    def wait(self, timeout=None):
        return self._returncode

    def kill(self):
        self._returncode = -9


def test_comfy_process_manager_start_invokes_subprocess_with_config(monkeypatch) -> None:
    dummy = _DummyProcess()
    popen_mock = mock.Mock(return_value=dummy)
    monkeypatch.setattr("subprocess.Popen", popen_mock)

    cfg = ComfyProcessConfig(
        command=["python", "main.py"],
        working_dir="C:/ComfyUI",
        env_overrides={"A": "1"},
    )
    manager = ComfyProcessManager(cfg)

    process = manager.start()

    assert process is dummy
    assert manager.owns_process is True
    kwargs = popen_mock.call_args.kwargs
    assert kwargs["cwd"] == "C:/ComfyUI"
    assert kwargs["env"]["A"] == "1"


@pytest.mark.parametrize("endpoint_state", ["healthy", "occupied"])
def test_comfy_start_refuses_any_occupied_configured_endpoint(monkeypatch, endpoint_state) -> None:
    popen_mock = mock.Mock()
    monkeypatch.setattr("subprocess.Popen", popen_mock)
    monkeypatch.setattr(
        "src.video.comfy_process_manager.probe_comfy_endpoint",
        lambda *_args, **_kwargs: endpoint_state,
    )
    manager = ComfyProcessManager(
        ComfyProcessConfig(command=["python", "main.py"], base_url="http://127.0.0.1:8188")
    )

    with pytest.raises(ComfyStartupError):
        manager.start()

    popen_mock.assert_not_called()
    assert manager.owns_process is False


def test_comfy_start_free_endpoint_launches_once_and_owned_stop_works(monkeypatch) -> None:
    dummy = _DummyProcess()
    popen_mock = mock.Mock(return_value=dummy)
    monkeypatch.setattr("subprocess.Popen", popen_mock)
    monkeypatch.setattr(
        "src.video.comfy_process_manager.probe_comfy_endpoint",
        lambda *_args, **_kwargs: "free",
    )
    manager = ComfyProcessManager(
        ComfyProcessConfig(command=["python", "main.py"], base_url="http://127.0.0.1:8188")
    )

    manager.start()
    assert manager.owns_process is True
    assert manager.restart(wait_ready=False) is True
    assert popen_mock.call_count == 2
    manager.stop()
    assert manager.owns_process is False


def test_comfy_process_manager_ensure_running_uses_healthcheck(monkeypatch) -> None:
    manager = ComfyProcessManager(ComfyProcessConfig(command=["python", "main.py"]))
    manager._process = _DummyProcess()
    start_mock = mock.Mock()
    manager.start = start_mock
    manager.check_health = mock.Mock(return_value=True)

    assert manager.ensure_running() is True
    start_mock.assert_not_called()


def test_comfy_process_manager_healthcheck_uses_configured_timeout_and_poll(monkeypatch) -> None:
    observed: dict[str, object] = {}

    def wait(base_url: str, *, timeout: float, poll_interval: float) -> bool:
        observed.update(base_url=base_url, timeout=timeout, poll_interval=poll_interval)
        return True

    monkeypatch.setattr("src.video.comfy_process_manager.wait_for_comfy_ready", wait)
    manager = ComfyProcessManager(
        ComfyProcessConfig(
            command=["python", "main.py"],
            base_url="http://127.0.0.1:9000",
            startup_timeout_seconds=30.0,
            poll_interval_seconds=0.25,
        )
    )

    assert manager.check_health() is True
    assert observed == {
        "base_url": "http://127.0.0.1:9000",
        "timeout": 30.0,
        "poll_interval": 0.25,
    }


@pytest.mark.parametrize(
    ("return_code", "expected_process_state"),
    [(None, "process=alive"), (23, "process=exited (return code 23)")],
)
def test_owned_comfy_startup_failure_reports_bounded_process_diagnostics(
    monkeypatch, return_code, expected_process_state
) -> None:
    dummy = _DummyProcess(pid=24680)
    dummy._returncode = return_code
    manager = ComfyProcessManager(
        ComfyProcessConfig(
            command=["python", "main.py"],
            base_url="http://127.0.0.1:9000",
            startup_timeout_seconds=30.0,
        )
    )
    manager._process = dummy
    manager._owns_process = True
    manager._stdout_tail.extend(["starting"] + ["x" * 300])
    manager._stderr_tail.append("launcher warning")

    def timeout(*_args, **_kwargs) -> bool:
        raise ComfyHealthCheckTimeout("not ready")

    monkeypatch.setattr("src.video.comfy_process_manager.wait_for_comfy_ready", timeout)

    with pytest.raises(ComfyStartupError) as caught:
        manager.check_health()

    message = str(caught.value)
    assert "pid=24680" in message
    assert expected_process_state in message
    assert "endpoint=http://127.0.0.1:9000" in message
    assert "timeout_seconds=30.0" in message
    assert "stdout_tail=['starting', '" in message
    assert "stderr_tail=['launcher warning']" in message
    assert "x" * 241 not in message


def test_comfy_process_manager_captures_output_tails(monkeypatch) -> None:
    dummy = _DummyProcess(stdout_text="ready\nserving\n", stderr_text="warn\n")
    monkeypatch.setattr("subprocess.Popen", mock.Mock(return_value=dummy))

    manager = ComfyProcessManager(ComfyProcessConfig(command=["python", "main.py"]))
    manager.start()
    manager._join_output_threads()

    assert manager.get_stdout_tail() == ["ready", "serving"]
    assert manager.get_stderr_tail() == ["warn"]


def test_build_default_comfy_process_config_reads_settings(tmp_path: Path) -> None:
    manager = ConfigManager(presets_dir=tmp_path / "presets")
    manager.save_settings(
        {
            "comfy_base_url": "http://127.0.0.1:9000",
            "comfy_workdir": str(tmp_path / "ComfyUI"),
            "comfy_command": ["python", "main.py"],
            "comfy_autostart_enabled": True,
            "comfy_health_total_timeout_seconds": 45.0,
        }
    )

    config = build_default_comfy_process_config(manager)

    assert config is not None
    assert config.base_url == "http://127.0.0.1:9000"
    assert config.command == ["python", "main.py"]
    assert config.autostart_enabled is True
    assert config.startup_timeout_seconds == 45.0


def test_build_default_comfy_process_config_autostarts_when_command_configured(
    tmp_path: Path,
) -> None:
    manager = ConfigManager(presets_dir=tmp_path / "presets")
    manager.save_settings(
        {
            "comfy_base_url": "http://127.0.0.1:9000",
            "comfy_workdir": str(tmp_path / "ComfyUI"),
            "comfy_command": ["python", "main.py"],
            "comfy_health_total_timeout_seconds": 45.0,
        }
    )

    config = build_default_comfy_process_config(manager)

    assert config is not None
    assert config.autostart_enabled is True
