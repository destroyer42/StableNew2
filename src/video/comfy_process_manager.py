from __future__ import annotations

import os
import subprocess
import threading
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.utils.config import ConfigManager
from src.video.comfy_healthcheck import wait_for_comfy_ready


@dataclass
class ComfyProcessConfig:
    command: list[str]
    working_dir: str | None = None
    env_overrides: Mapping[str, str] | None = None
    startup_timeout_seconds: float = 60.0
    poll_interval_seconds: float = 0.5
    auto_restart_on_crash: bool = False
    autostart_enabled: bool = False
    base_url: str | None = None

    def build_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env.update(self.env_overrides or {})
        return env


class ComfyStartupError(RuntimeError):
    """Raised when the managed Comfy process fails to start."""


_GLOBAL_COMFY_PROCESS_MANAGER: ComfyProcessManager | None = None


class ComfyProcessManager:
    """Owns the lifecycle of a managed local ComfyUI process."""

    def __init__(self, config: ComfyProcessConfig) -> None:
        global _GLOBAL_COMFY_PROCESS_MANAGER
        self._config = config
        self._process: subprocess.Popen | None = None
        self._stdout_tail: deque[str] = deque(maxlen=200)
        self._stderr_tail: deque[str] = deque(maxlen=200)
        self._stdout_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._stopped = False
        _GLOBAL_COMFY_PROCESS_MANAGER = self

    @property
    def process(self) -> subprocess.Popen | None:
        return self._process

    @property
    def pid(self) -> int | None:
        return None if self._process is None else getattr(self._process, "pid", None)

    def get_stdout_tail(self) -> list[str]:
        return list(self._stdout_tail)

    def get_stderr_tail(self) -> list[str]:
        return list(self._stderr_tail)

    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self) -> subprocess.Popen:
        if self._process and self.is_running():
            return self._process
        try:
            process = subprocess.Popen(
                self._config.command,
                cwd=self._config.working_dir,
                env=self._config.build_env(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                text=True,
                bufsize=1,
                shell=False,
            )
        except Exception as exc:  # noqa: BLE001
            raise ComfyStartupError(str(exc)) from exc

        self._process = process
        self._stopped = False
        self._stdout_thread = self._start_output_thread(process.stdout, self._stdout_tail)
        self._stderr_thread = self._start_output_thread(process.stderr, self._stderr_tail)
        return process

    def stop(self, *, grace_seconds: float = 5.0) -> None:
        global _GLOBAL_COMFY_PROCESS_MANAGER
        if self._stopped:
            return
        self._stopped = True
        process = self._process
        if process is not None and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=grace_seconds)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass
        self._process = None
        self._join_output_threads()
        if _GLOBAL_COMFY_PROCESS_MANAGER is self:
            _GLOBAL_COMFY_PROCESS_MANAGER = None

    def check_health(self) -> bool:
        base_url = self._configured_base_url()
        return wait_for_comfy_ready(
            base_url,
            timeout=15.0,
            poll_interval=1.0,
        )

    def ensure_running(self) -> bool:
        if self.is_running():
            try:
                if self.check_health():
                    return True
            except Exception:
                pass
            self.stop()
        self.start()
        return self.check_health()

    def restart(
        self,
        *,
        wait_ready: bool = True,
    ) -> bool:
        self.stop()
        self.start()
        if not wait_ready:
            return True
        try:
            return self.check_health()
        except Exception:
            return False

    def _configured_base_url(self) -> str:
        if self._config.base_url:
            return self._config.base_url
        return os.environ.get("STABLENEW_COMFY_BASE_URL", "http://127.0.0.1:8188")

    def _start_output_thread(
        self,
        stream: Any,
        sink: deque[str],
    ) -> threading.Thread | None:
        if stream is None:
            return None

        def _reader() -> None:
            try:
                while True:
                    line = stream.readline()
                    if not line:
                        break
                    sink.append(str(line).rstrip())
            except Exception:
                return

        thread = threading.Thread(target=_reader, daemon=True)
        thread.start()
        return thread

    def _join_output_threads(self) -> None:
        for thread in (self._stdout_thread, self._stderr_thread):
            if thread is not None and thread.is_alive():
                thread.join(timeout=1.0)
        self._stdout_thread = None
        self._stderr_thread = None


def get_global_comfy_process_manager() -> ComfyProcessManager | None:
    return _GLOBAL_COMFY_PROCESS_MANAGER


def clear_global_comfy_process_manager() -> None:
    global _GLOBAL_COMFY_PROCESS_MANAGER
    _GLOBAL_COMFY_PROCESS_MANAGER = None


def build_default_comfy_process_config(
    config_manager: ConfigManager | None = None,
) -> ComfyProcessConfig | None:
    manager = config_manager or ConfigManager()
    raw_settings = manager._load_settings()
    settings = manager.load_settings()
    command = list(settings.get("comfy_command") or [])
    if not command:
        env_command = os.environ.get("STABLENEW_COMFY_COMMAND", "").split()
        command = [part for part in env_command if part]
    if not command:
        return None
    working_dir = str(settings.get("comfy_workdir") or "").strip() or None
    if working_dir:
        working_dir = str(Path(working_dir))
    autostart_enabled = raw_settings.get("comfy_autostart_enabled")
    if autostart_enabled is None:
        autostart_enabled = bool(command)
    return ComfyProcessConfig(
        command=command,
        working_dir=working_dir,
        autostart_enabled=bool(autostart_enabled),
        base_url=str(settings.get("comfy_base_url") or "http://127.0.0.1:8188"),
        startup_timeout_seconds=float(settings.get("comfy_health_total_timeout_seconds") or 30.0),
    )


__all__ = [
    "ComfyProcessConfig",
    "ComfyProcessManager",
    "ComfyStartupError",
    "build_default_comfy_process_config",
    "clear_global_comfy_process_manager",
    "get_global_comfy_process_manager",
]
