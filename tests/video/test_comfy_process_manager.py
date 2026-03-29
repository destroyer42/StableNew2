from __future__ import annotations

import io
from pathlib import Path
from unittest import mock

from src.utils.config import ConfigManager
from src.video.comfy_process_manager import (
    ComfyProcessConfig,
    ComfyProcessManager,
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
    kwargs = popen_mock.call_args.kwargs
    assert kwargs["cwd"] == "C:/ComfyUI"
    assert kwargs["env"]["A"] == "1"


def test_comfy_process_manager_ensure_running_uses_healthcheck(monkeypatch) -> None:
    manager = ComfyProcessManager(ComfyProcessConfig(command=["python", "main.py"]))
    manager._process = _DummyProcess()
    start_mock = mock.Mock()
    manager.start = start_mock
    manager.check_health = mock.Mock(return_value=True)

    assert manager.ensure_running() is True
    start_mock.assert_not_called()


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


def test_build_default_comfy_process_config_autostarts_when_command_configured(tmp_path: Path) -> None:
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
