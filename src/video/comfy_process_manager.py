from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from src.utils.config import ConfigManager
from src.utils.managed_process import ManagedProcess
from src.video.comfy_healthcheck import probe_comfy_endpoint, wait_for_comfy_ready

# Anchored to the repository, not the working directory, and size-rotated by ``ManagedProcess``.
_MANAGED_COMFY_LOG_PATH = (
    Path(__file__).resolve().parents[2] / "logs" / "comfy" / "managed_comfy.log"
)


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
    log_path: Path | None = None

    def build_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env.update(self.env_overrides or {})
        return env


class ComfyStartupError(RuntimeError):
    """Raised when the managed Comfy process fails to start."""


_GLOBAL_COMFY_PROCESS_MANAGER: ComfyProcessManager | None = None


class ComfyProcessManager:
    """Owns the lifecycle of a managed local ComfyUI process.

    The child runs inside a ``ManagedProcess``: it is placed in its own OS container at launch (so a hard crash of this
    application cannot orphan it, and ``stop`` reaps its whole tree), its output is drained and decoded safely on
    bounded readers, and its log rotates.  Nothing outside this launch session is ever adopted or stopped.
    """

    def __init__(
        self,
        config: ComfyProcessConfig,
        *,
        process_factory: Callable[..., ManagedProcess] = ManagedProcess,
    ) -> None:
        global _GLOBAL_COMFY_PROCESS_MANAGER
        self._config = config
        self._process_factory = process_factory
        self._managed: ManagedProcess | None = None
        self._last_tails: tuple[list[str], list[str]] = ([], [])
        self._stopped = False
        _GLOBAL_COMFY_PROCESS_MANAGER = self

    @property
    def process(self) -> subprocess.Popen | None:
        return None if self._managed is None else self._managed.process

    @property
    def owns_process(self) -> bool:
        """Whether this manager owns the process created by its current launch session."""
        return self.process is not None

    @property
    def pid(self) -> int | None:
        return None if self._managed is None else self._managed.pid

    @property
    def contained(self) -> bool:
        """Whether the OS accepted the child into its own container (kill-on-close)."""
        return bool(self._managed is not None and self._managed.contained)

    def get_stdout_tail(self) -> list[str]:
        return self._last_tails[0] if self._managed is None else self._managed.stdout_tail()

    def get_stderr_tail(self) -> list[str]:
        return self._last_tails[1] if self._managed is None else self._managed.stderr_tail()

    def is_running(self) -> bool:
        return self._managed is not None and self._managed.is_running()

    def start(self) -> subprocess.Popen:
        if self._managed is not None and self.is_running():
            process = self._managed.process
            if process is not None:
                return process
        if self._config.base_url:
            endpoint_state = probe_comfy_endpoint(self._config.base_url, timeout=0.5)
            if endpoint_state != "free":
                detail = (
                    "a healthy external ComfyUI is already serving"
                    if endpoint_state == "healthy"
                    else "the configured endpoint is occupied but is not valid ComfyUI"
                )
                raise ComfyStartupError(
                    f"Cannot launch managed ComfyUI: {detail}; refusing to adopt, stop, or replace it"
                )
        managed = self._process_factory(
            self._config.command,
            cwd=self._config.working_dir,
            env=self._config.build_env(),
            label="comfy",
            log_path=self._config.log_path,
        )
        try:
            process = managed.start()
        except Exception as exc:  # noqa: BLE001
            managed.stop(grace_seconds=0.0)
            raise ComfyStartupError(str(exc)) from exc

        self._managed = managed
        self._stopped = False
        # stop() unregisters this manager; a relaunch must re-register it, or the owned process
        # it just started would be invisible to runtime transitions (PR-RUNTIME-100) that look
        # the Comfy owner up through get_global_comfy_process_manager().
        global _GLOBAL_COMFY_PROCESS_MANAGER
        _GLOBAL_COMFY_PROCESS_MANAGER = self
        return process

    def stop(self, *, grace_seconds: float = 5.0) -> None:
        global _GLOBAL_COMFY_PROCESS_MANAGER
        if self._stopped:
            return
        self._stopped = True
        managed, self._managed = self._managed, None
        if managed is not None:
            managed.stop(grace_seconds=grace_seconds)
            self._last_tails = (managed.stdout_tail(), managed.stderr_tail())
        if _GLOBAL_COMFY_PROCESS_MANAGER is self:
            _GLOBAL_COMFY_PROCESS_MANAGER = None

    def check_health(self) -> bool:
        base_url = self._configured_base_url()
        try:
            return wait_for_comfy_ready(
                base_url,
                timeout=self._config.startup_timeout_seconds,
                poll_interval=self._config.poll_interval_seconds,
            )
        except Exception as exc:
            if self.owns_process:
                raise ComfyStartupError(self._startup_failure_detail(base_url, exc)) from exc
            raise

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
        if not self.owns_process:
            return False
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

    def _startup_failure_detail(self, base_url: str, error: Exception) -> str:
        """Return bounded diagnostics for a failed process this manager owns.

        The manager already retains bounded output tails.  Including them here
        preserves the state available at readiness failure before an owner
        releases its process, without discovering or inspecting any external
        runtime.
        """

        process = self.process
        pid = getattr(process, "pid", None)
        return_code = process.poll() if process is not None else None
        process_state = "alive" if return_code is None else f"exited (return code {return_code})"
        return (
            "Managed ComfyUI did not become ready "
            f"(pid={pid}, process={process_state}, endpoint={base_url}, "
            f"timeout_seconds={self._config.startup_timeout_seconds}): {error}; "
            f"stdout_tail={self._bounded_output_tail(self.get_stdout_tail())!r}; "
            f"stderr_tail={self._bounded_output_tail(self.get_stderr_tail())!r}"
        )

    @staticmethod
    def _bounded_output_tail(lines: list[str]) -> list[str]:
        return [line[:240] for line in lines[-10:]]


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
        log_path=_MANAGED_COMFY_LOG_PATH,
    )


__all__ = [
    "ComfyProcessConfig",
    "ComfyProcessManager",
    "ComfyStartupError",
    "build_default_comfy_process_config",
    "clear_global_comfy_process_manager",
    "get_global_comfy_process_manager",
]
