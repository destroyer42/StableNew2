from __future__ import annotations

import json
import logging
import os
import platform
import signal
import subprocess
import threading
import time
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.utils import LogContext, get_logger, log_with_ctx
from src.utils.logging_helpers_v2 import build_run_session_id, format_launch_message


class WebUIStartupError(RuntimeError):
    """Raised when WebUI fails to start."""


logger = get_logger(__name__)


_WEBUI_CACHE_FILE = Path(__file__).parent.parent.parent / "data" / "webui_cache.json"


def _load_webui_cache() -> dict[str, Any]:
    """Load cached WebUI configuration."""
    try:
        if _WEBUI_CACHE_FILE.exists():
            with _WEBUI_CACHE_FILE.open("r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_webui_cache(cache: dict[str, Any]) -> None:
    """Save WebUI configuration to cache."""
    try:
        _WEBUI_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _WEBUI_CACHE_FILE.open("w") as f:
            json.dump(cache, f, indent=2)
    except Exception:
        pass


@dataclass
class WebUIProcessConfig:
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


class WebUIProcessManager:
    """Owns the lifecycle of the external WebUI process."""

    def __init__(self, config: WebUIProcessConfig) -> None:
        self._config = config
        self._process: subprocess.Popen | None = None
        self._last_exit_code: int | None = None
        self._start_time: float | None = None
        self._health_cache: bool | None = None
        self._pid: int | None = None
        self._stdout_tail: deque[str] = deque(maxlen=200)
        self._stderr_tail: deque[str] = deque(maxlen=200)
        self._stopped: bool = False
        global _GLOBAL_WEBUI_PROCESS_MANAGER
        _GLOBAL_WEBUI_PROCESS_MANAGER = self

    @property
    def process(self) -> subprocess.Popen | None:
        return self._process

    def ensure_running(self) -> bool:
        ctx = LogContext(subsystem="api")
        logging.info("WebUI ensure_running check requested")
        if self.is_running():
            logging.info("WebUI process already running; verifying health")
            try:
                healthy = self.check_health()
                if healthy:
                    log_with_ctx(logger, logging.INFO, "WebUI already healthy", ctx=ctx)
                    return True
                logging.warning("Existing WebUI process unhealthy; restarting")
            except Exception:
                logging.warning("Health check failed while WebUI claimed running")
            self.stop()

        try:
            self.start()
        except Exception:
            log_with_ctx(logger, logging.ERROR, "Failed to start WebUI process", ctx=ctx)
            return False

        try:
            healthy = self.check_health()
        except Exception:
            healthy = False
        log_with_ctx(
            logger,
            logging.INFO if healthy else logging.ERROR,
            "WebUI health check",
            ctx=ctx,
            extra_fields={"healthy": healthy},
        )
        return healthy

    def check_health(self) -> bool:
        if self._config.base_url:
            url = self._config.base_url
        else:
            url = os.environ.get("STABLENEW_WEBUI_BASE_URL", "http://127.0.0.1:7860")
        from src.api.healthcheck import wait_for_webui_ready

        try:
            return wait_for_webui_ready(url, timeout=15.0, poll_interval=3.0)
        except Exception:
            return False

    def start(self) -> subprocess.Popen:
        """Start the WebUI process if not already running."""

        if self._process and self.is_running():
            return self._process

        import logging

        ctx = LogContext(subsystem="api")
        log_with_ctx(
            logger,
            logging.INFO,
            "Starting WebUI process",
            ctx=ctx,
            extra_fields={"command": self._config.command, "working_dir": self._config.working_dir},
        )
        run_session_id = build_run_session_id()

        try:
            # CRITICAL FIX: Don't capture stdout/stderr at all - let WebUI write directly to console
            # This prevents any potential file locking or buffer blocking issues
            
            self._process = subprocess.Popen(
                self._config.command,
                cwd=self._config.working_dir or None,
                env=self._config.build_env(),
                stdout=None,  # Inherit parent's stdout (console)
                stderr=None,  # Inherit parent's stderr (console)
                shell=True if (os.name == "nt" and self._config.command[0].endswith(".bat")) else False,
            )
            self._pid = self._process.pid
            self._start_time = time.time()
            launch_msg = format_launch_message(
                run_session_id=run_session_id,
                pid=self._pid,
                command=self._config.command,
                cwd=self._config.working_dir,
            )
            logger.info(launch_msg)
            logger.info("WebUI stdout/stderr will appear directly in console (not captured)")
            self._stdout_tail.clear()
            self._stderr_tail.clear()
        except Exception as exc:  # noqa: BLE001 - surface structured error
            raise WebUIStartupError(f"Failed to start WebUI: {exc}") from exc

        return self._process

    def stop(self) -> None:
        """Attempt to terminate the process if running (idempotent)."""
        if self._stopped:
            return
        self._stopped = True
        try:
            self.stop_webui()
        except Exception:
            logger.exception("Error calling stop_webui during stop()")
        finally:
            # Clear global reference to allow cleanup
            clear_global_webui_process_manager()

    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def shutdown(self, grace_seconds: float = 10.0) -> bool:
        return self.stop_webui(grace_seconds)

    def stop_webui(self, grace_seconds: float = 10.0) -> bool:
        """Attempt to stop (gracefully then forcefully) the WebUI process."""

        process = self._process
        if process is None:
            return True
        # PR-CORE1-D15: Ensure .terminated attribute exists for test doubles
        if not hasattr(process, "terminated"):
            process.terminated = False
        if process.poll() is not None:
            self._finalize_process(process)
            # Already exited; terminated remains False
            return True
        pid = getattr(process, "pid", None)
        logger.info("Initiating WebUI shutdown (pid=%s, grace=%.1fs)", pid, grace_seconds)
        try:
            process.terminate()
            process.terminated = True
        except Exception:
            pass

        elapsed = 0.0
        interval = min(0.25, max(0.05, grace_seconds / 40.0))
        while elapsed < grace_seconds:
            if process.poll() is not None:
                break
            time.sleep(interval)
            elapsed += interval

        if process.poll() is None:
            try:
                process.kill()
            except Exception:
                pass
            try:
                process.wait(timeout=2.0)
            except Exception:
                pass
            if process.poll() is None:
                self._kill_process_tree(getattr(process, "pid", None))

        self._finalize_process(process)
        exit_code = self._last_exit_code
        running = self.is_running()
        logger.info(
            "WebUI shutdown complete (pid=%s, exit_code=%s, running=%s)",
            getattr(process, "pid", None),
            exit_code,
            running,
        )
        return not self.is_running()

    def restart_webui(
        self,
        *,
        wait_ready: bool = True,
        max_attempts: int = 6,
        base_delay: float = 1.0,
        max_delay: float = 8.0,
    ) -> bool:
        """Restart the WebUI process and wait for its API to become available."""

        ctx = LogContext(subsystem="api")
        log_with_ctx(logger, logging.INFO, "Restarting WebUI process", ctx=ctx)
        self.stop_webui()
        try:
            self.start()
        except Exception as exc:
            log_with_ctx(
                logger,
                logging.ERROR,
                "Failed to restart WebUI process",
                ctx=ctx,
                extra_fields={"error": str(exc)} if exc else {},
            )
            return False

        if not wait_ready:
            return True

        client = None
        ready = False
        base_url = self._configured_base_url()
        try:
            from src.api.client import SDWebUIClient
            from src.api.webui_api import WebUIAPI, WebUIReadinessTimeout

            client = SDWebUIClient(base_url=base_url)
            helper = WebUIAPI(client=client)

            # Use true-readiness gate (API + boot marker)
            try:
                helper.wait_until_true_ready(
                    timeout_s=60.0,
                    poll_interval_s=2.0,
                    get_stdout_tail=self.get_stdout_tail_text,
                )
                ready = True
                log_with_ctx(
                    logger,
                    logging.INFO,
                    "WebUI TRUE-READY confirmed after restart",
                    ctx=ctx,
                )
            except WebUIReadinessTimeout as e:
                log_with_ctx(
                    logger,
                    logging.ERROR,
                    "WebUI true-readiness timeout after restart",
                    ctx=ctx,
                    extra_fields={
                        "total_waited_s": e.total_waited,
                        "checks": str(e.checks_status),
                        "stdout_tail_snippet": e.stdout_tail[:500] if e.stdout_tail else "",
                    },
                )
                ready = False
        except Exception as exc:  # pragma: no cover - best effort
            log_with_ctx(
                logger,
                logging.ERROR,
                "WebUI readiness check failed after restart",
                ctx=ctx,
                extra_fields={
                    "error": str(exc),
                    "base_url": base_url,
                }
                if exc
                else {},
            )
            ready = False
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass

        log_with_ctx(
            logger,
            logging.INFO if ready else logging.ERROR,
            "WebUI restart readiness",
            ctx=ctx,
            extra_fields={
                "ready": ready,
                "base_url": base_url,
            },
        )
        return ready

    def _finalize_process(self, process: subprocess.Popen) -> None:
        try:
            if process.stdout:
                process.stdout.close()
        except Exception:
            pass
        try:
            if process.stderr:
                process.stderr.close()
        except Exception:
            pass
        try:
            self._last_exit_code = process.poll()
        except Exception:
            self._last_exit_code = None
        finally:
            self._log_process_crash_tail(self._last_exit_code)
            self._process = None
            self._pid = None

    def get_status(self) -> dict[str, Any]:
        return {
            "running": self.is_running(),
            "pid": getattr(self._process, "pid", None) if self._process else None,
            "start_time": self._start_time,
            "last_exit_code": self._last_exit_code
            if self._process is None
            else self._process.poll(),
            "command": list(self._config.command),
            "working_dir": self._config.working_dir,
        }

    def _configured_base_url(self) -> str:
        if self._config.base_url:
            return self._config.base_url
        return os.environ.get("STABLENEW_WEBUI_BASE_URL", "http://127.0.0.1:7860")

    @property
    def pid(self) -> int | None:
        return self._pid

    def _kill_process_tree(self, pid: int | None) -> None:
        if pid is None:
            return
        try:
            if platform.system() == "Windows":
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    check=False,
                    capture_output=True,
                )
            else:
                try:
                    os.killpg(pid, signal.SIGTERM)
                except Exception:
                    os.kill(pid, signal.SIGTERM)
        except Exception:
            logger.exception("Failed to kill WebUI process tree for pid %s", pid)

    def _log_process_crash_tail(self, exit_code: int | None) -> None:
        if exit_code is None:
            return
        stdout_tail = "\n".join(self._stdout_tail) if self._stdout_tail else "<empty>"
        stderr_tail = "\n".join(self._stderr_tail) if self._stderr_tail else "<empty>"
        log_fn = logger.error if exit_code != 0 else logger.info
        log_fn(
            "WebUI process exited (code=%s). Recent stdout:\n%s\nRecent stderr:\n%s",
            exit_code,
            stdout_tail,
            stderr_tail,
        )

    def get_recent_output_tail(self, max_lines: int = 200) -> dict[str, Any]:
        """Return the latest stdout/stderr tail plus process metadata."""

        def _join_tail(buffer: deque[str]) -> str:
            if not buffer:
                return ""
            lines = list(buffer)
            if max_lines > 0 and len(lines) > max_lines:
                lines = lines[-max_lines:]
            return "\n".join(lines)

        return {
            "stdout_tail": _join_tail(self._stdout_tail),
            "stderr_tail": _join_tail(self._stderr_tail),
            "pid": self.pid,
            "running": self.is_running(),
        }

    def get_stdout_tail_text(self, max_lines: int = 200) -> str:
        """Get stdout tail as plain text (for readiness checking)."""
        if not self._stdout_tail:
            return ""
        lines = list(self._stdout_tail)
        if max_lines > 0 and len(lines) > max_lines:
            lines = lines[-max_lines:]
        return "\n".join(lines)


def detect_default_webui_workdir(base_dir: str | None = None) -> str | None:
    """Attempt to locate a stable-diffusion-webui folder near the repo."""

    root = Path(base_dir or os.getcwd()).resolve()
    candidates = [root, root.parent, root.parent.parent]
    for candidate in candidates:
        target = candidate / "stable-diffusion-webui"
        if not target.exists() or not target.is_dir():
            continue
        if os.name == "nt":
            if (target / "webui-user.bat").exists():
                return str(target)
        else:
            if (target / "webui.sh").exists():
                return str(target)
    return None


def build_default_webui_process_config() -> WebUIProcessConfig | None:
    """Build a WebUIProcessConfig using app_config defaults and detection."""

    try:
        from src.config import app_config
    except Exception:
        return None

    # First try cached location
    cache = _load_webui_cache()
    cached_workdir = cache.get("workdir")
    cached_command = cache.get("command")

    if cached_workdir and cached_command:
        workdir_path = Path(cached_workdir)
        if workdir_path.exists() and workdir_path.is_dir():
            # Verify the cached command still exists
            command_path = workdir_path / cached_command[0] if cached_command else None
            if command_path and command_path.exists():
                print(f"Using cached WebUI location: {cached_workdir}")
                config = WebUIProcessConfig(
                    command=cached_command,
                    working_dir=cached_workdir,
                    autostart_enabled=app_config.is_webui_autostart_enabled(),
                    base_url=os.environ.get("STABLENEW_WEBUI_BASE_URL", "http://127.0.0.1:7860"),
                )
                return config

    # Fall back to app config
    workdir = app_config.get_webui_workdir()
    command = app_config.get_webui_command()

    if workdir and command:
        # Cache this valid configuration
        print(f"Caching WebUI location: {workdir}")
        _save_webui_cache({"workdir": workdir, "command": command, "timestamp": time.time()})
        return WebUIProcessConfig(
            command=command,
            working_dir=workdir,
            autostart_enabled=app_config.is_webui_autostart_enabled(),
            base_url=os.environ.get("STABLENEW_WEBUI_BASE_URL", "http://127.0.0.1:7860"),
        )

    # Last resort: detect automatically (expensive)
    print("No cached or configured WebUI location found, performing auto-detection...")
    workdir = detect_default_webui_workdir()
    if workdir:
        workdir_path = Path(workdir)
        # Determine command based on platform
        if os.name == "nt":
            command = ["webui-user.bat", "--api", "--xformers"]
        else:
            command = ["bash", "webui.sh", "--api"]

        # Verify command exists
        command_path = workdir_path / command[0]
        if command_path.exists():
            # Cache the detected configuration
            print(f"Caching detected WebUI location: {workdir}")
            _save_webui_cache({"workdir": workdir, "command": command, "timestamp": time.time()})
            return WebUIProcessConfig(
                command=command,
                working_dir=workdir,
                autostart_enabled=app_config.is_webui_autostart_enabled(),
                base_url=os.environ.get("STABLENEW_WEBUI_BASE_URL", "http://127.0.0.1:7860"),
            )

    return None


_GLOBAL_WEBUI_PROCESS_MANAGER: WebUIProcessManager | None = None


def get_global_webui_process_manager() -> WebUIProcessManager | None:
    return _GLOBAL_WEBUI_PROCESS_MANAGER


def clear_global_webui_process_manager() -> None:
    """Clear the global WebUI process manager reference (idempotent)."""
    global _GLOBAL_WEBUI_PROCESS_MANAGER
    _GLOBAL_WEBUI_PROCESS_MANAGER = None
