from __future__ import annotations

import os
import subprocess
import json
import logging
from dataclasses import dataclass, field
from typing import Mapping, Any
from pathlib import Path
import time

from src.utils import get_logger, LogContext, log_with_ctx


class WebUIStartupError(RuntimeError):
    """Raised when WebUI fails to start."""


logger = get_logger(__name__)


_WEBUI_CACHE_FILE = Path(__file__).parent.parent.parent / "data" / "webui_cache.json"


def _load_webui_cache() -> dict[str, Any]:
    """Load cached WebUI configuration."""
    try:
        if _WEBUI_CACHE_FILE.exists():
            with _WEBUI_CACHE_FILE.open('r') as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_webui_cache(cache: dict[str, Any]) -> None:
    """Save WebUI configuration to cache."""
    try:
        _WEBUI_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _WEBUI_CACHE_FILE.open('w') as f:
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
        env.update({k: v for k, v in (self.env_overrides or {}).items()})
        return env


class WebUIProcessManager:
    """Owns the lifecycle of the external WebUI process."""

    def __init__(self, config: WebUIProcessConfig) -> None:
        self._config = config
        self._process: subprocess.Popen | None = None
        self._last_exit_code: int | None = None
        self._start_time: float | None = None
        self._health_cache: bool | None = None

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

        try:
            self._process = subprocess.Popen(
                self._config.command,
                cwd=self._config.working_dir or None,
                env=self._config.build_env(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=os.name == "nt" and self._config.command[0].endswith(".bat"),  # Use shell for .bat files on Windows
            )
            self._start_time = time.time()
            # Log process output in background
            import threading
            import logging
            def log_output(stream, name):
                try:
                    for line in iter(stream.readline, b''):
                        logging.info(f"WebUI {name}: {line.decode().strip()}")
                except Exception:
                    pass
            threading.Thread(target=log_output, args=(self._process.stdout, "stdout"), daemon=True).start()
            threading.Thread(target=log_output, args=(self._process.stderr, "stderr"), daemon=True).start()
        except Exception as exc:  # noqa: BLE001 - surface structured error
            raise WebUIStartupError(f"Failed to start WebUI: {exc}") from exc

        return self._process

    def stop(self) -> None:
        """Attempt to terminate the process if running."""

        self.stop_webui()

    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def shutdown(self, grace_seconds: float = 10.0) -> bool:
        return self.stop_webui(grace_seconds)

    def stop_webui(self, grace_seconds: float = 10.0) -> bool:
        """Attempt to stop (gracefully then forcefully) the WebUI process."""

        process = self._process
        if process is None:
            return True
        if process.poll() is not None:
            self._finalize_process(process)
            return True
        try:
            process.terminate()
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

        self._finalize_process(process)
        return not self.is_running()

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
            self._process = None

    def get_status(self) -> dict[str, Any]:
        return {
            "running": self.is_running(),
            "pid": getattr(self._process, "pid", None) if self._process else None,
            "start_time": self._start_time,
            "last_exit_code": self._last_exit_code if self._process is None else self._process.poll(),
            "command": list(self._config.command),
            "working_dir": self._config.working_dir,
        }


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
    cached_workdir = cache.get('workdir')
    cached_command = cache.get('command')
    
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
        _save_webui_cache({
            'workdir': workdir,
            'command': command,
            'timestamp': time.time()
        })
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
            _save_webui_cache({
                'workdir': workdir,
                'command': command,
                'timestamp': time.time()
            })
            return WebUIProcessConfig(
                command=command,
                working_dir=workdir,
                autostart_enabled=app_config.is_webui_autostart_enabled(),
                base_url=os.environ.get("STABLENEW_WEBUI_BASE_URL", "http://127.0.0.1:7860"),
            )

    return None
