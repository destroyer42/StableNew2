from __future__ import annotations

import sys
import time
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
    def __init__(self, pid: int = 54321) -> None:
        self.pid = pid
        self._returncode = None

    def poll(self):
        return self._returncode


class _FakeManaged:
    """Stands in for ManagedProcess so lifecycle logic is tested without spawning anything."""

    instances: list[_FakeManaged] = []

    def __init__(self, command, **kwargs) -> None:
        self.command = list(command)
        self.kwargs = kwargs
        self.process = None
        self.stopped = False
        self.contained = True
        self._stdout: list[str] = []
        self._stderr: list[str] = []
        _FakeManaged.instances.append(self)

    @property
    def pid(self):
        return None if self.process is None else self.process.pid

    def start(self):
        self.process = _DummyProcess()
        return self.process

    def stop(self, *, grace_seconds: float = 5.0) -> None:
        self.stopped = True

    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def stdout_tail(self):
        return list(self._stdout)

    def stderr_tail(self):
        return list(self._stderr)


@pytest.fixture(autouse=True)
def _reset_fake_managed():
    _FakeManaged.instances.clear()
    yield
    _FakeManaged.instances.clear()


def _manager(config: ComfyProcessConfig) -> ComfyProcessManager:
    return ComfyProcessManager(config, process_factory=_FakeManaged)


def test_comfy_process_manager_start_invokes_the_managed_process_with_config() -> None:
    cfg = ComfyProcessConfig(
        command=["python", "main.py"],
        working_dir="C:/ComfyUI",
        env_overrides={"A": "1"},
    )
    manager = _manager(cfg)

    process = manager.start()

    (managed,) = _FakeManaged.instances
    assert process is managed.process
    assert manager.owns_process is True
    assert managed.command == ["python", "main.py"]
    assert managed.kwargs["cwd"] == "C:/ComfyUI"
    assert managed.kwargs["env"]["A"] == "1"
    assert managed.kwargs["label"] == "comfy"
    assert manager.contained is True


@pytest.mark.parametrize("endpoint_state", ["healthy", "occupied"])
def test_comfy_start_refuses_any_occupied_configured_endpoint(monkeypatch, endpoint_state) -> None:
    monkeypatch.setattr(
        "src.video.comfy_process_manager.probe_comfy_endpoint",
        lambda *_args, **_kwargs: endpoint_state,
    )
    manager = _manager(
        ComfyProcessConfig(command=["python", "main.py"], base_url="http://127.0.0.1:8188")
    )

    with pytest.raises(ComfyStartupError):
        manager.start()

    assert _FakeManaged.instances == []
    assert manager.owns_process is False


def test_comfy_start_free_endpoint_launches_once_and_owned_stop_works(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.video.comfy_process_manager.probe_comfy_endpoint",
        lambda *_args, **_kwargs: "free",
    )
    manager = _manager(
        ComfyProcessConfig(command=["python", "main.py"], base_url="http://127.0.0.1:8188")
    )

    manager.start()
    assert manager.owns_process is True
    assert manager.restart(wait_ready=False) is True
    assert len(_FakeManaged.instances) == 2
    assert _FakeManaged.instances[0].stopped is True
    manager.stop()
    assert _FakeManaged.instances[1].stopped is True
    assert manager.owns_process is False


def test_comfy_process_manager_ensure_running_uses_healthcheck(monkeypatch) -> None:
    manager = _manager(ComfyProcessConfig(command=["python", "main.py"]))
    manager.start()
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
    manager = _manager(
        ComfyProcessConfig(
            command=["python", "main.py"],
            base_url="http://127.0.0.1:9000",
            startup_timeout_seconds=30.0,
        )
    )
    manager.start()
    managed = _FakeManaged.instances[0]
    managed.process = _DummyProcess(pid=24680)
    managed.process._returncode = return_code
    managed._stdout.extend(["starting"] + ["x" * 300])
    managed._stderr.append("launcher warning")

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


def test_comfy_process_manager_captures_output_tails_from_a_real_child() -> None:
    code = "import sys; print('ready'); print('serving'); print('warn', file=sys.stderr)"
    manager = ComfyProcessManager(ComfyProcessConfig(command=[sys.executable, "-c", code]))
    try:
        manager.start()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not (
            manager.get_stdout_tail() == ["ready", "serving"]
            and manager.get_stderr_tail() == ["warn"]
        ):
            time.sleep(0.05)
        assert manager.get_stdout_tail() == ["ready", "serving"]
        assert manager.get_stderr_tail() == ["warn"]
    finally:
        manager.stop()
    # The tails survive stop() for post-mortem diagnostics.
    assert manager.get_stdout_tail() == ["ready", "serving"]


def test_a_failed_launch_is_reported_as_a_startup_error_and_leaves_no_owner() -> None:
    manager = ComfyProcessManager(
        ComfyProcessConfig(command=[str(Path("definitely") / "missing" / "comfy.exe")])
    )
    with pytest.raises(ComfyStartupError):
        manager.start()
    assert manager.owns_process is False


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
