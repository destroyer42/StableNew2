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
from urllib.parse import urlparse

from src.utils import LogContext, get_logger, log_with_ctx
from src.utils.logging_helpers_v2 import build_run_session_id, format_launch_message
from src.utils.process_container_v2 import (
    ProcessContainer,
    ProcessContainerConfig,
    build_process_container,
)


class WebUIStartupError(RuntimeError):
    """Raised when WebUI fails to start.
    
    IMPORTANT: WebUI start/ensure_running/restart methods now check if the StableNew GUI
    is actually running before starting WebUI. This prevents orphaned processes from
    crashed/improperly-shutdown sessions from auto-restarting WebUI indefinitely.
    
    The check uses SingleInstanceLock.is_gui_running() to verify the GUI's TCP lock is held.
    If the GUI is not running, WebUI start/restart operations are blocked with a warning.
    """


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


def _normalize_process_path(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(Path(value).resolve()).lower().replace("\\", "/")
    except Exception:
        return str(value).strip().lower().replace("\\", "/")


def _command_basename(arg: Any) -> str:
    try:
        return Path(str(arg)).name.lower()
    except Exception:
        return str(arg).strip().lower()


def _cmdline_contains_webui_launch(cmdline: list[str] | tuple[str, ...] | None) -> bool:
    launch_names = {
        "launch.py",
        "webui.py",
        "webui-user.bat",
        "webui-user.sh",
        "webui.bat",
    }
    return any(_command_basename(arg) in launch_names for arg in (cmdline or []))


def _cmdline_mentions_workdir(
    cmdline: list[str] | tuple[str, ...] | None,
    working_dir: str | None,
) -> bool:
    normalized_workdir = _normalize_process_path(working_dir)
    if not normalized_workdir:
        return False
    return any(
        normalized_workdir in _normalize_process_path(str(arg))
        for arg in (cmdline or [])
    )


def _get_webui_python_match_reasons(
    *,
    process_name: str | None,
    cmdline: list[str] | tuple[str, ...] | None,
    cwd: str | None,
    working_dir: str | None,
) -> list[str]:
    name = (process_name or "").lower()
    if "python" not in name:
        return []

    reasons: list[str] = []
    cwd_match = bool(working_dir) and _normalize_process_path(cwd) == _normalize_process_path(working_dir)
    launch_match = _cmdline_contains_webui_launch(cmdline)
    cmdline_workdir_match = _cmdline_mentions_workdir(cmdline, working_dir)

    if cwd_match:
        reasons.append("cwd matches webui_dir")
    if launch_match and cmdline_workdir_match:
        reasons.append("launch script under webui_dir")
    elif launch_match and cwd_match:
        reasons.append("launch script from webui cwd")

    return reasons


def _get_webui_shell_match_reasons(
    *,
    process_name: str | None,
    cmdline: list[str] | tuple[str, ...] | None,
    cwd: str | None,
    working_dir: str | None,
) -> list[str]:
    name = (process_name or "").lower()
    if name not in {"cmd.exe", "conhost.exe", "powershell.exe", "pwsh.exe", "bash.exe"}:
        return []

    reasons: list[str] = []
    cwd_match = bool(working_dir) and _normalize_process_path(cwd) == _normalize_process_path(working_dir)
    launch_match = _cmdline_contains_webui_launch(cmdline)
    cmdline_workdir_match = _cmdline_mentions_workdir(cmdline, working_dir)

    if cwd_match and launch_match:
        reasons.append("shell cwd matches webui_dir and launch script present")
    elif launch_match and cmdline_workdir_match:
        reasons.append("shell launch command targets webui_dir")

    return reasons


@dataclass
class WebUIProcessConfig:
    command: list[str]
    working_dir: str | None = None
    env_overrides: Mapping[str, str] | None = None
    launch_profile: str = "standard"
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
        self._stdout_log_path: Path | None = None
        self._stderr_log_path: Path | None = None
        self._stdout_log_file = None
        self._stderr_log_file = None
        self._stdout_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._stopped: bool = False
        self._orphan_monitor_thread: threading.Thread | None = None
        self._orphan_monitor_stop = threading.Event()
        self._process_container: ProcessContainer | None = None
        self._init_process_container()
        global _GLOBAL_WEBUI_PROCESS_MANAGER
        _GLOBAL_WEBUI_PROCESS_MANAGER = self

    def _init_process_container(self) -> None:
        """Create an OS-level process container for deterministic WebUI lifecycle."""
        try:
            self._process_container = build_process_container(
                "webui_process_manager",
                ProcessContainerConfig(enabled=True),
            )
        except Exception as exc:
            logger.debug("Failed to initialize WebUI process container: %s", exc)
            self._process_container = None

    def _attach_pid_to_container(self, pid: int | None) -> None:
        if pid is None or self._process_container is None:
            return
        try:
            self._process_container.add_pid(pid)
        except Exception as exc:
            logger.debug("Failed to attach WebUI PID %s to process container: %s", pid, exc)

    def _teardown_process_container(self) -> None:
        container = self._process_container
        if container is None:
            return
        try:
            container.kill_all()
        except Exception:
            logger.debug("WebUI process container kill_all failed", exc_info=True)
        try:
            container.teardown()
        except Exception:
            logger.debug("WebUI process container teardown failed", exc_info=True)
        self._process_container = None

    @property
    def process(self) -> subprocess.Popen | None:
        return self._process

    def get_launch_profile(self) -> str:
        return str(self._config.launch_profile or "standard")

    def set_launch_profile(self, profile: str) -> None:
        from src.config import app_config

        normalized = str(profile or "standard").strip() or "standard"
        self._config.launch_profile = normalized
        self._config.command = list(app_config.resolve_webui_launch_command(normalized))
        app_config.set_webui_launch_profile(normalized)

    def ensure_running(self) -> bool:
        # Note: The orphan monitor thread now handles preventing orphaned processes.
        # We don't need to check SingleInstanceLock here during normal startup,
        # as it would block legitimate WebUI launches during app initialization.
        
        ctx = LogContext(subsystem="api")
        logger.debug("WebUI ensure_running check requested")
        if self.is_running():
            logger.debug("WebUI process already running; verifying health")
            try:
                healthy = self.check_health()
                if healthy:
                    log_with_ctx(logger, logging.DEBUG, "WebUI already healthy", ctx=ctx)
                    return True
                logger.warning("Existing WebUI process unhealthy; restarting")
            except Exception:
                logger.warning("Health check failed while WebUI claimed running")
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
            # PR-PORT-DISCOVERY: If health check failed on expected port, try to discover
            # WebUI on alternate ports in case previous shutdown left orphan on port 7860
            # and WebUI auto-incremented to 7861
            logger.warning("[PORT-DISCOVERY] Health check failed on %s, scanning for WebUI on alternate ports...", url)
            try:
                discovered_port = discover_webui_port(base_port=7860, max_offset=10)
                if discovered_port and discovered_port != 7860:
                    logger.warning(
                        "[PORT-DISCOVERY] ⚠ Found WebUI on port %d instead of expected 7860. "
                        "This indicates an orphaned process was blocking port 7860. "
                        "Updating base_url to use discovered port.",
                        discovered_port
                    )
                    # Update the config to use the discovered port
                    self._config.base_url = f"http://127.0.0.1:{discovered_port}"
                    # Try health check again with the correct port
                    return wait_for_webui_ready(self._config.base_url, timeout=5.0, poll_interval=1.0)
            except Exception as exc:
                logger.debug("[PORT-DISCOVERY] Port discovery failed: %s", exc)
            
            return False

    def start(self) -> subprocess.Popen:
        """Start the WebUI process if not already running."""
        
        # CRITICAL: Don't start WebUI if StableNew GUI is not running
        # This prevents orphaned processes from crashed sessions from spawning WebUI
        from src.utils.single_instance import SingleInstanceLock
        if not SingleInstanceLock.is_gui_running():
            error_msg = (
                "WebUI start requested but StableNew GUI is not running. "
                "Refusing to start WebUI to prevent orphaned process. "
                "This may indicate an orphaned queue runner or background process from a crashed session."
            )
            logger.error(error_msg)
            raise RuntimeError(error_msg)

        if self._process and self.is_running():
            return self._process

        import logging

        ctx = LogContext(subsystem="api")
        log_with_ctx(
            logger,
            logging.DEBUG,
            "Starting WebUI process",
            ctx=ctx,
            extra_fields={
                "command": self._config.command,
                "working_dir": self._config.working_dir,
                "launch_profile": self._config.launch_profile,
                "event": "webui_process_start",
            },
        )
        run_session_id = build_run_session_id()

        try:
            # PR-PORT-DISCOVERY: Clean up any orphaned WebUI processes blocking the target port
            # This handles cases where a previous StableNew session crashed and left WebUI running
            # Extract port from base_url (default to 7860 if not specified)
            port = 7860
            if self._config.base_url:
                try:
                    from urllib.parse import urlparse
                    parsed = urlparse(self._config.base_url)
                    if parsed.port:
                        port = parsed.port
                except Exception:
                    pass
            
            killed_orphans = kill_orphaned_webui_processes_blocking_port(
                port=port, 
                working_dir=self._config.working_dir
            )
            if killed_orphans:
                logger.info(
                    "[PORT-DISCOVERY] Cleaned up %d orphaned process(es) blocking port %d: %s",
                    len(killed_orphans), port, killed_orphans
                )
                # Give the OS time to release the port
                time.sleep(1.0)
            
            # Prevention-first launch policy:
            # - Never use shell=True (detaches child trees and complicates ownership).
            # - For .bat/.cmd on Windows, invoke through cmd.exe explicitly so we can keep
            #   shell=False and retain deterministic process/container ownership.
            launch_command = list(self._config.command)
            if (
                os.name == "nt"
                and launch_command
                and launch_command[0].lower().endswith((".bat", ".cmd"))
            ):
                launch_command = ["cmd.exe", "/d", "/s", "/c", *launch_command]

            launch_in_new_console = False
            if os.name == "nt":
                launch_in_new_console = os.environ.get(
                    "STABLENEW_WEBUI_NEW_CONSOLE", ""
                ).strip().lower() in {"1", "true", "yes", "on"}

            # On Windows, use CREATE_NEW_PROCESS_GROUP only (no BREAKAWAY):
            # keeping the process in our job/container avoids detached orphan trees.
            creationflags = 0
            if os.name == "nt":
                import subprocess
                # CREATE_NEW_PROCESS_GROUP = 0x00000200
                creationflags = 0x00000200
                if launch_in_new_console:
                    # CREATE_NEW_CONSOLE = 0x00000010
                    creationflags |= 0x00000010

            # Optional debug mode: launch WebUI in its own console window so users can
            # observe native startup/runtime logs directly.
            popen_stdout = subprocess.PIPE
            popen_stderr = subprocess.PIPE
            if launch_in_new_console:
                popen_stdout = None
                popen_stderr = None

            self._process = subprocess.Popen(
                launch_command,
                cwd=self._config.working_dir or None,
                env=self._config.build_env(),
                stdout=popen_stdout,
                stderr=popen_stderr,
                shell=False,
                creationflags=creationflags if os.name == "nt" else 0,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
            self._pid = self._process.pid
            self._attach_pid_to_container(self._pid)
            self._start_time = time.time()
            launch_msg = format_launch_message(
                run_session_id=run_session_id,
                pid=self._pid,
                command=self._config.command,
                cwd=self._config.working_dir,
            )
            logger.debug(launch_msg)
            log_with_ctx(
                logger,
                logging.INFO,
                "WebUI launch profile resolved",
                ctx=ctx,
                extra_fields={
                    "event": "webui_launch_profile_resolved",
                    "launch_profile": self._config.launch_profile,
                    "pid": self._pid,
                },
            )
            self._stdout_tail.clear()
            self._stderr_tail.clear()
            self._start_output_capture(run_session_id)
            
            # Start orphan monitor thread to kill WebUI if StableNew GUI exits
            self._start_orphan_monitor()
        except Exception as exc:  # noqa: BLE001 - surface structured error
            raise WebUIStartupError(f"Failed to start WebUI: {exc}") from exc

        return self._process

    def _start_output_capture(self, run_session_id: str) -> None:
        process = self._process
        if process is None:
            return
        if process.stdout is None or process.stderr is None:
            logger.warning("WebUI stdout/stderr capture unavailable (no pipes attached)")
            return

        log_dir = Path("logs") / "webui"
        log_dir.mkdir(parents=True, exist_ok=True)
        self._stdout_log_path = log_dir / f"webui_stdout_{run_session_id}.log"
        self._stderr_log_path = log_dir / f"webui_stderr_{run_session_id}.log"
        self._stdout_log_file = self._stdout_log_path.open("a", encoding="utf-8", errors="replace")
        self._stderr_log_file = self._stderr_log_path.open("a", encoding="utf-8", errors="replace")

        def _read_stream(stream, sink, tail, label: str) -> None:
            try:
                for line in iter(stream.readline, ""):
                    if not line:
                        break
                    tail.append(line.rstrip("\n"))
                    try:
                        sink.write(line)
                        sink.flush()
                    except Exception:
                        pass
            except Exception as exc:  # pragma: no cover - best effort
                logger.debug("WebUI %s reader stopped: %s", label, exc)
            finally:
                try:
                    stream.close()
                except Exception:
                    pass

        # PR-THREAD-001: Use ThreadRegistry for stream readers
        from src.utils.thread_registry import get_thread_registry
        registry = get_thread_registry()
        
        self._stdout_thread = registry.spawn(
            target=_read_stream,
            args=(process.stdout, self._stdout_log_file, self._stdout_tail, "stdout"),
            name="WebUI-stdout-reader",
            daemon=False,
            purpose="Read WebUI process stdout stream"
        )
        self._stderr_thread = registry.spawn(
            target=_read_stream,
            args=(process.stderr, self._stderr_log_file, self._stderr_tail, "stderr"),
            name="WebUI-stderr-reader",
            daemon=False,
            purpose="Read WebUI process stderr stream"
        )
        # Threads already started by ThreadRegistry.spawn()
        logger.debug(
            "WebUI stdout/stderr captured to %s and %s",
            str(self._stdout_log_path),
            str(self._stderr_log_path),
        )

    def _stop_output_capture(self) -> None:
        from src.utils.thread_registry import get_thread_registry

        registry = get_thread_registry()
        for stream in (
            getattr(self._process, "stdout", None),
            getattr(self._process, "stderr", None),
        ):
            try:
                if stream is not None:
                    stream.close()
            except Exception:
                pass
        # PR-SHUTDOWN-FIX: Increase timeout to 5s since stdout/stderr threads
        # may be blocked reading from pipes that take time to close
        for attr_name in ("_stdout_thread", "_stderr_thread"):
            thread = getattr(self, attr_name, None)
            if thread and thread.is_alive():
                thread.join(timeout=5.0)
            if thread is not None:
                registry.unregister(thread)
            setattr(self, attr_name, None)
        for handle in (self._stdout_log_file, self._stderr_log_file):
            try:
                if handle is not None:
                    handle.flush()
                    handle.close()
            except Exception:
                pass
        self._stdout_log_file = None
        self._stderr_log_file = None

    def stop(self) -> None:
        """Attempt to terminate the process if running (idempotent)."""
        if self._stopped:
            return
        self._stopped = True
        # Stop orphan monitor first
        self._stop_orphan_monitor()
        try:
            self.stop_webui()
        except Exception:
            logger.exception("Error calling stop_webui during stop()")
        finally:
            # Clear global reference to allow cleanup
            self._teardown_process_container()
            clear_global_webui_process_manager()

    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def shutdown(self, grace_seconds: float = 10.0) -> bool:
        return self.stop_webui(grace_seconds)

    def stop_webui(self, grace_seconds: float = 10.0) -> bool:
        """Attempt to stop (gracefully then forcefully) the WebUI process."""
        
        logger.info("=" * 72)
        logger.info("STOP_WEBUI CALLED (grace_seconds=%.1f)", grace_seconds)
        logger.info("=" * 72)

        process = self._process
        if process is None:
            logger.info("stop_webui called but no process tracked")
            return True
        # PR-CORE1-D15: Ensure .terminated attribute exists for test doubles
        if not hasattr(process, "terminated"):
            process.terminated = False
        if process.poll() is not None:
            logger.info("stop_webui called but process already exited")
            self._stop_output_capture()
            self._finalize_process(process)
            # Already exited; terminated remains False
            return True
        pid = getattr(process, "pid", None)
        logger.info("Initiating WebUI shutdown (pid=%s, grace=%.1fs)", pid, grace_seconds)
        
        # Try graceful termination first
        try:
            process.terminate()
            process.terminated = True
            logger.info("Sent terminate signal to PID %s", pid)
        except Exception as exc:
            logger.warning("Failed to terminate PID %s: %s", pid, exc)

        # Wait for graceful shutdown
        elapsed = 0.0
        interval = min(0.25, max(0.05, grace_seconds / 40.0))
        graceful_exit = False
        while elapsed < grace_seconds:
            if process.poll() is not None:
                logger.info("Process %s exited gracefully after %.1fs", pid, elapsed)
                graceful_exit = True
                break
            time.sleep(interval)
            elapsed += interval

        # If still running, force kill
        if process.poll() is None:
            logger.warning("Process %s did not exit gracefully, forcing kill", pid)
            try:
                process.kill()
                logger.info("Sent kill signal to PID %s", pid)
            except Exception as exc:
                logger.warning("Failed to kill PID %s: %s", pid, exc)
            try:
                process.wait(timeout=2.0)
                logger.info("Process %s exited after kill signal", pid)
            except Exception as exc:
                logger.warning("Process %s did not exit after kill, using taskkill: %s", pid, exc)
            
            # Last resort: kill entire process tree
            if process.poll() is None:
                self._kill_process_tree(getattr(process, "pid", None))

        # ALWAYS kill child processes, even if main process exited gracefully
        # (WebUI spawns child workers that don't die with the parent)
        if graceful_exit:
            logger.info("Main WebUI process exited gracefully, now cleaning up child processes...")
            self._kill_process_tree(pid)  # Kill children even after graceful exit
        
        self._stop_output_capture()
        self._finalize_process(process)
        exit_code = self._last_exit_code
        running = self.is_running()
        logger.info(
            "WebUI shutdown complete (pid=%s, exit_code=%s, running=%s)",
            getattr(process, "pid", None),
            exit_code,
            running,
        )
        
        # Final verification
        if running:
            logger.error(
                "WebUI process %s is STILL RUNNING after shutdown attempt! Check Task Manager.",
                pid,
            )
        
        return not self.is_running()

    def restart_webui(
        self,
        *,
        wait_ready: bool = True,
        max_attempts: int = 6,
        base_delay: float = 1.0,
        max_delay: float = 8.0,
        profile_override: str | None = None,
    ) -> bool:
        """Restart the WebUI process and wait for its API to become available."""

        # CRITICAL: Don't restart WebUI if StableNew GUI is not running
        from src.utils.single_instance import SingleInstanceLock
        if not SingleInstanceLock.is_gui_running():
            logger.warning(
                "WebUI restart requested but StableNew GUI is not running. "
                "Refusing to restart WebUI to prevent orphaned process."
            )
            return False

        ctx = LogContext(subsystem="api")
        log_with_ctx(logger, logging.INFO, "Restarting WebUI process", ctx=ctx)
        if profile_override:
            try:
                self.set_launch_profile(profile_override)
            except Exception as exc:
                log_with_ctx(
                    logger,
                    logging.ERROR,
                    "Failed to apply WebUI launch profile override",
                    ctx=ctx,
                    extra_fields={"profile_override": profile_override, "error": str(exc)},
                )
                return False
        base_url = self._configured_base_url()
        try:
            from src.api.healthcheck import clear_readiness_failure_state

            clear_readiness_failure_state(base_url)
        except Exception:
            logger.debug("Failed to clear readiness failure state before restart", exc_info=True)
        attempts = max(1, int(max_attempts))
        base_delay_s = max(0.0, float(base_delay))
        max_delay_s = max(0.0, float(max_delay))

        for attempt_index in range(1, attempts + 1):
            ready = False
            try:
                self.stop_webui()
            except Exception as exc:
                log_with_ctx(
                    logger,
                    logging.WARNING,
                    "Failed to stop WebUI before restart attempt",
                    ctx=ctx,
                    extra_fields={
                        "attempt": attempt_index,
                        "max_attempts": attempts,
                        "error": str(exc),
                        "launch_profile": self.get_launch_profile(),
                    },
                )

            try:
                self.start()
            except Exception as exc:
                log_with_ctx(
                    logger,
                    logging.ERROR,
                    "Failed to restart WebUI process",
                    ctx=ctx,
                    extra_fields={
                        "attempt": attempt_index,
                        "max_attempts": attempts,
                        "error": str(exc),
                        "launch_profile": self.get_launch_profile(),
                    },
                )
                ready = False
            else:
                if not wait_ready:
                    ready = True
                else:
                    client = None
                    try:
                        from src.api.client import SDWebUIClient
                        from src.api.webui_api import WebUIAPI, WebUIReadinessTimeout

                        client = SDWebUIClient(base_url=base_url)
                        helper = WebUIAPI(client=client)
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
                            extra_fields={
                                "attempt": attempt_index,
                                "max_attempts": attempts,
                                "launch_profile": self.get_launch_profile(),
                            },
                        )
                    except WebUIReadinessTimeout as exc:
                        log_with_ctx(
                            logger,
                            logging.ERROR,
                            "WebUI true-readiness timeout after restart",
                            ctx=ctx,
                            extra_fields={
                                "attempt": attempt_index,
                                "max_attempts": attempts,
                                "total_waited_s": exc.total_waited,
                                "checks": str(exc.checks_status),
                                "stdout_tail_snippet": exc.stdout_tail[:500] if exc.stdout_tail else "",
                                "launch_profile": self.get_launch_profile(),
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
                                "attempt": attempt_index,
                                "max_attempts": attempts,
                                "error": str(exc),
                                "base_url": base_url,
                                "launch_profile": self.get_launch_profile(),
                            },
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
                logging.INFO if ready else logging.WARNING,
                "WebUI restart attempt result",
                ctx=ctx,
                extra_fields={
                    "attempt": attempt_index,
                    "max_attempts": attempts,
                    "ready": ready,
                    "base_url": base_url,
                    "launch_profile": self.get_launch_profile(),
                },
            )
            if ready:
                return True
            if attempt_index < attempts:
                delay_s = base_delay_s * (2 ** (attempt_index - 1)) if base_delay_s > 0 else 0.0
                if max_delay_s > 0:
                    delay_s = min(delay_s, max_delay_s)
                if delay_s > 0:
                    time.sleep(delay_s)

        return False

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
        """Kill the process and all WebUI-related python.exe processes.
        
        PR-PROCESS-CLEANUP: Enhanced to handle CMD parent processes and their
        Python children. When WebUI is launched via .bat file with shell=True,
        the tracked PID is the CMD shell, and the actual Python WebUI process
        is a child that must also be killed.
        """
        if pid is None:
            logger.warning("_kill_process_tree called with None pid")
            return
        
        logger.info("Forcefully killing WebUI process tree for PID %s", pid)
        
        if platform.system() == "Windows":
            # Kill all python.exe processes that look like WebUI
            try:
                import psutil
                killed_pids = []
                
                # PR-PROCESS-CLEANUP: Check if the tracked PID is a CMD shell
                # If so, we need to kill its Python children AND the CMD parent
                is_cmd_parent = False
                try:
                    tracked_proc = psutil.Process(pid)
                    tracked_name = tracked_proc.name().lower()
                    if 'cmd' in tracked_name or 'powershell' in tracked_name or 'bash' in tracked_name:
                        is_cmd_parent = True
                        logger.warning(
                            "Tracked PID %s is a shell wrapper (%s) - will kill shell AND Python children",
                            pid, tracked_proc.name()
                        )
                except psutil.NoSuchProcess:
                    pass
                
                # First, try to kill the tracked PID and its children
                try:
                    parent = psutil.Process(pid)
                    children = parent.children(recursive=True)
                    logger.info("Found %d direct child processes for PID %s", len(children), pid)
                    
                    # PR-PROCESS-CLEANUP: Kill children first (includes Python WebUI processes)
                    for child in children:
                        try:
                            child_name = child.name()
                            logger.info("Killing direct child process PID %s (%s)", child.pid, child_name)
                            child.kill()
                            child.wait(timeout=2.0)  # Wait for confirmation
                            killed_pids.append(child.pid)
                        except psutil.TimeoutExpired:
                            logger.warning("Child PID %s did not exit after kill, using taskkill", child.pid)
                            self._force_kill_with_taskkill(child.pid)
                        except psutil.NoSuchProcess:
                            pass
                        except Exception as exc:
                            logger.warning("Failed to kill child PID %s: %s", child.pid, exc)
                    
                    # Kill parent (CMD shell if shell=True was used)
                    try:
                        parent.kill()
                        logger.info("Killed parent process PID %s (%s)", pid, parent.name())
                        killed_pids.append(pid)
                    except psutil.NoSuchProcess:
                        pass
                except psutil.NoSuchProcess:
                    logger.info("Parent process %s already gone", pid)
                except Exception as exc:
                    logger.warning("Failed to enumerate children of PID %s: %s", pid, exc)
                
                # AGGRESSIVE: Find and kill ALL python.exe processes that might be WebUI
                # This catches orphaned processes that aren't direct children
                webui_dir = self._config.working_dir
                logger.warning("=" * 80)
                logger.warning("STARTING AGGRESSIVE WEBUI PROCESS CLEANUP")
                logger.warning("Working directory: %s", webui_dir)
                logger.warning("=" * 80)
                
                # DIAGNOSTIC: List ALL python.exe processes BEFORE cleanup
                logger.warning(">>> LISTING ALL PYTHON.EXE PROCESSES BEFORE CLEANUP:")
                all_python_pids = []
                webui_candidate_pids = set()
                for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'cwd', 'memory_info']):
                    try:
                        if proc.info['name'] and 'python' in proc.info['name'].lower():
                            cmdline = proc.info.get('cmdline') or []
                            cwd = proc.info.get('cwd', '')
                            mem_info = proc.info.get('memory_info')
                            mem_mb = mem_info.rss / (1024 * 1024) if mem_info else 0
                            all_python_pids.append(proc.pid)
                            match_reason = _get_webui_python_match_reasons(
                                process_name=proc.info.get('name'),
                                cmdline=cmdline,
                                cwd=cwd,
                                working_dir=webui_dir,
                            )
                            if match_reason:
                                webui_candidate_pids.add(proc.pid)
                            logger.warning(
                                "  PID %s: name=%s, mem=%.1f MB, cwd=%s, cmdline=%s",
                                proc.pid,
                                proc.info['name'],
                                mem_mb,
                                cwd[:60] + "..." if len(cwd) > 60 else cwd,
                                ' '.join(cmdline[:3]) if cmdline else "N/A",
                            )
                    except Exception:
                        pass
                logger.warning(">>> Found %d total python.exe processes", len(all_python_pids))
                logger.warning("")
                
                logger.info("Scanning for orphaned WebUI python.exe processes (working_dir=%s)", webui_dir)
                
                for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'cwd', 'memory_info']):
                    try:
                        # Skip already-killed processes
                        if proc.pid in killed_pids:
                            continue
                        
                        # Look for python.exe
                        if proc.info['name'] and 'python' in proc.info['name'].lower():
                            cmdline = proc.info.get('cmdline') or []
                            cwd = proc.info.get('cwd', '')
                            mem_info = proc.info.get('memory_info')
                            mem_mb = mem_info.rss / (1024 * 1024) if mem_info else 0
                            
                            match_reason = _get_webui_python_match_reasons(
                                process_name=proc.info.get('name'),
                                cmdline=cmdline,
                                cwd=cwd,
                                working_dir=webui_dir,
                            )
                            is_webui = bool(match_reason)
                            
                            # DIAGNOSTIC: Log WHY we're killing or NOT killing each process
                            if is_webui:
                                logger.warning(
                                    ">>> KILLING PID %s: %s (cwd=%s, mem=%.1f MB) - Reasons: %s",
                                    proc.pid,
                                    ' '.join(cmdline[:2]) if cmdline else proc.info['name'],
                                    cwd[:40] + "..." if len(cwd) > 40 else cwd,
                                    mem_mb,
                                    ', '.join(match_reason),
                                )
                                try:
                                    proc.kill()
                                    logger.info("✓ Successfully killed PID %s", proc.pid)
                                    killed_pids.append(proc.pid)
                                except Exception as kill_exc:
                                    logger.error("✗ FAILED to kill PID %s: %s", proc.pid, kill_exc)
                            else:
                                logger.debug(
                                    "Skipping PID %s (mem=%.1f MB): No WebUI match",
                                    proc.pid,
                                    mem_mb,
                                )
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                    except Exception as exc:
                        logger.debug("Error checking process: %s", exc)
                
                logger.warning("")
                logger.warning(">>> CLEANUP COMPLETE: Killed %d WebUI-related processes", len(killed_pids))
                logger.warning(">>> PIDs killed: %s", killed_pids if killed_pids else "NONE")
                
                # DIAGNOSTIC: List ALL python.exe processes AFTER cleanup
                logger.warning("")
                logger.warning(">>> LISTING ALL PYTHON.EXE PROCESSES AFTER CLEANUP:")
                remaining_python_pids = []
                for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'memory_info']):
                    try:
                        if proc.info['name'] and 'python' in proc.info['name'].lower():
                            mem_info = proc.info.get('memory_info')
                            mem_mb = mem_info.rss / (1024 * 1024) if mem_info else 0
                            remaining_python_pids.append(proc.pid)
                            was_supposed_to_die = proc.pid in webui_candidate_pids and proc.pid not in killed_pids
                            status = "⚠ LEAKED" if mem_mb > 500 else "OK (small)"
                            logger.warning(
                                "  PID %s: mem=%.1f MB %s%s",
                                proc.pid,
                                mem_mb,
                                status,
                                " (SHOULD HAVE BEEN KILLED!)" if was_supposed_to_die and mem_mb > 500 else "",
                            )
                    except Exception:
                        pass
                logger.warning(">>> %d python.exe processes remain (started with %d)", 
                             len(remaining_python_pids), len(all_python_pids))
                logger.warning("=" * 80)
                
                # PR-PROCESS-001: Kill cmd.exe and conhost.exe shell wrappers
                # These are left behind when .bat/.cmd files spawn python.exe then exit
                logger.warning("")
                logger.warning(">>> SCANNING FOR CMD/SHELL WRAPPER PROCESSES:")
                shell_pids_killed = []
                
                for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'cwd', 'memory_info']):
                    try:
                        name = proc.info['name']
                        if name:
                            cmdline = proc.info.get('cmdline', [])
                            cwd = proc.info.get('cwd', '')
                            mem_info = proc.info.get('memory_info')
                            mem_mb = mem_info.rss / (1024 * 1024) if mem_info else 0
                            match_reason = _get_webui_shell_match_reasons(
                                process_name=name,
                                cmdline=cmdline,
                                cwd=cwd,
                                working_dir=webui_dir,
                            )
                            if match_reason:
                                logger.warning(
                                    ">>> Killing shell process: PID=%s name=%s cwd=%s mem=%.1fMB cmdline=%s - Reasons: %s",
                                    proc.pid,
                                    name,
                                    cwd[:40] + "..." if len(cwd) > 40 else cwd,
                                    mem_mb,
                                    ' '.join(cmdline[:3]) if cmdline else "N/A",
                                    ', '.join(match_reason),
                                )
                                proc.kill()
                                shell_pids_killed.append(proc.pid)
                                logger.info("✓ Successfully killed shell wrapper PID %s", proc.pid)
                                    
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                    except Exception as exc:
                        logger.debug("Error checking shell process: %s", exc)
                
                if shell_pids_killed:
                    logger.warning(
                        ">>> Killed %d shell wrapper processes: %s",
                        len(shell_pids_killed), shell_pids_killed
                    )
                else:
                    logger.warning(">>> No shell wrapper processes found")
                logger.warning("=" * 80)
                
                logger.info("Killed %d WebUI-related processes (python: %d, shell: %d)", 
                           len(killed_pids) + len(shell_pids_killed), len(killed_pids), len(shell_pids_killed))
                
            except ImportError:
                logger.error("psutil not available - cannot kill orphaned processes! Install psutil.")
                self._taskkill_tree(pid)
            except Exception as exc:
                logger.exception("Failed to kill WebUI processes: %s", exc)
                self._taskkill_tree(pid)
        else:
            # Unix-like systems
            try:
                os.killpg(pid, signal.SIGTERM)
                logger.info("Sent SIGTERM to process group %s", pid)
            except Exception as exc:
                logger.warning("Failed to kill process group %s, trying single process: %s", pid, exc)
                try:
                    os.kill(pid, signal.SIGTERM)
                    logger.info("Sent SIGTERM to process %s", pid)
                except Exception as kill_exc:
                    logger.exception("Failed to kill process %s: %s", pid, kill_exc)

    def _taskkill_tree(self, pid: int) -> None:
        """Use Windows taskkill to kill process tree."""
        try:
            result = subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                logger.info("Successfully killed process tree for PID %s via taskkill", pid)
            else:
                logger.warning(
                    "taskkill returned code %s for PID %s: %s",
                    result.returncode,
                    pid,
                    result.stderr.strip() if result.stderr else "no error message",
                )
        except Exception as exc:
            logger.exception("taskkill failed for PID %s: %s", pid, exc)

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
            "stdout_log_path": str(self._stdout_log_path) if self._stdout_log_path else "",
            "stderr_log_path": str(self._stderr_log_path) if self._stderr_log_path else "",
            "pid": self.pid,
            "running": self.is_running(),
            "launch_profile": self._config.launch_profile,
            "command": list(self._config.command),
            "working_dir": self._config.working_dir or "",
        }

    def get_stdout_tail_text(self, max_lines: int = 200) -> str:
        """Get stdout tail as plain text (for readiness checking)."""
        if not self._stdout_tail:
            return ""
        lines = list(self._stdout_tail)
        if max_lines > 0 and len(lines) > max_lines:
            lines = lines[-max_lines:]
        return "\n".join(lines)

    def _start_orphan_monitor(self) -> None:
        """Start background thread to monitor if GUI is still running."""
        if self._orphan_monitor_thread and self._orphan_monitor_thread.is_alive():
            return
        
        self._orphan_monitor_stop.clear()
        # PR-THREAD-001: Use ThreadRegistry for orphan monitor
        from src.utils.thread_registry import get_thread_registry
        registry = get_thread_registry()
        self._orphan_monitor_thread = registry.spawn(
            target=self._orphan_monitor_loop,
            name="WebUI-Orphan-Monitor",
            daemon=False,
            purpose="Monitor and cleanup orphaned WebUI processes"
        )
        logger.info("[Orphan Monitor] Started monitoring thread to prevent orphaned WebUI processes")

    def _stop_orphan_monitor(self) -> None:
        """Stop the orphan monitor thread."""
        from src.utils.thread_registry import get_thread_registry

        registry = get_thread_registry()
        self._orphan_monitor_stop.set()
        if self._orphan_monitor_thread and self._orphan_monitor_thread.is_alive():
            self._orphan_monitor_thread.join(timeout=2.0)
        if self._orphan_monitor_thread is not None:
            registry.unregister(self._orphan_monitor_thread)
        self._orphan_monitor_thread = None

    def _orphan_monitor_loop(self) -> None:
        """
        Monitor loop that checks if StableNew GUI is still running.
        
        PR-PROCESS-001: Enhanced to detect reparented WebUI processes and
        scan for orphaned processes without valid parents.
        """
        from src.utils.single_instance import SingleInstanceLock
        
        gui_pid = os.getpid()
        webui_dir = self._config.working_dir
        check_interval = 2.0  # Check every 2 seconds (increased from 5s for faster detection)
        
        logger.info(
            "[Orphan Monitor] Started: GUI_PID=%s, WebUI_PID=%s, check_interval=%.1fs",
            gui_pid, self.pid, check_interval
        )
        
        while not self._orphan_monitor_stop.is_set():
            try:
                # Check 1: GUI process still alive?
                if not SingleInstanceLock.is_gui_running():
                    logger.error(
                        "[Orphan Monitor] StableNew GUI has exited! "
                        "Terminating WebUI to prevent orphaned process (PID=%s)",
                        self._pid
                    )
                    # Force kill WebUI immediately
                    self._kill_all_webui_processes()
                    break
                
                # Check 2: WebUI process still running?
                if not self.is_running():
                    logger.debug("[Orphan Monitor] WebUI process has exited naturally, stopping monitor")
                    break
                
                # PR-PROCESS-001: Check 3: Scan for orphaned WebUI processes
                try:
                    import psutil
                    orphaned_webui_pids = self._scan_for_orphaned_webui_processes()
                    if orphaned_webui_pids:
                        logger.warning(
                            "[Orphan Monitor] Found %d orphaned WebUI processes: %s",
                            len(orphaned_webui_pids), orphaned_webui_pids
                        )
                        # Kill them if GUI is still alive
                        if SingleInstanceLock.is_gui_running():
                            for orphan_pid in orphaned_webui_pids:
                                try:
                                    psutil.Process(orphan_pid).kill()
                                    logger.warning("[Orphan Monitor] Killed orphan PID %s", orphan_pid)
                                except Exception as exc:
                                    logger.debug("Failed to kill orphan %s: %s", orphan_pid, exc)
                except ImportError:
                    pass  # psutil not available, skip orphan scan
                    
            except Exception as exc:
                logger.exception("[Orphan Monitor] Error in monitor loop: %s", exc)
            
            # Wait for next check or stop signal
            self._orphan_monitor_stop.wait(check_interval)
        
        logger.info("[Orphan Monitor] Stopped")

    def _scan_for_orphaned_webui_processes(self) -> list[int]:
        """
        Scan for WebUI python.exe processes that have no valid parent.
        
        PR-PROCESS-001: Detects processes that were reparented to system
        after shell wrapper exits.
        """
        try:
            import psutil
        except ImportError:
            return []
        
        webui_dir = self._config.working_dir
        orphans = []
        
        # Don't request 'cwd' upfront - get it separately with error handling
        for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'ppid']):
            try:
                name = proc.info['name']
                if not name or 'python' not in name.lower():
                    continue
                
                cmdline = proc.info.get('cmdline', [])
                ppid = proc.info.get('ppid')
                
                # Try to get cwd separately with error handling
                cwd = ''
                try:
                    cwd = proc.cwd()
                except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
                    # Process terminated, access denied, or cwd not available
                    pass
                
                is_webui = bool(
                    _get_webui_python_match_reasons(
                        process_name=proc.info.get('name'),
                        cmdline=cmdline,
                        cwd=cwd,
                        working_dir=webui_dir,
                    )
                )
                
                if is_webui and ppid:
                    # Check if parent is system or nonexistent
                    try:
                        parent = psutil.Process(ppid)
                        # System PIDs: 0 (System Idle), 1 (init/systemd), 4 (System on Windows)
                        if ppid in (0, 1, 4):
                            orphans.append(proc.pid)
                            logger.debug(
                                "[Orphan Monitor] Found reparented WebUI process: PID=%s, parent=%s",
                                proc.pid, ppid
                            )
                    except psutil.NoSuchProcess:
                        # Parent doesn't exist - process is orphaned
                        orphans.append(proc.pid)
                        logger.debug(
                            "[Orphan Monitor] Found orphaned WebUI process: PID=%s, parent PID=%s (dead)",
                            proc.pid, ppid
                        )
                        
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
            except Exception as exc:
                logger.debug("Error scanning for orphans: %s", exc)
        
        return orphans

    def cleanup_orphaned_webui_processes(self) -> list[int]:
        """Kill orphaned WebUI processes blocking the configured port/workdir."""

        base_url = self._configured_base_url()
        parsed = urlparse(base_url)
        port = parsed.port or 7860
        working_dir = self._config.working_dir
        return kill_orphaned_webui_processes_blocking_port(
            port=port,
            working_dir=working_dir,
        )

    def _force_kill_with_taskkill(self, pid: int) -> None:
        """Last resort: use Windows taskkill command to force-kill a process."""
        try:
            import subprocess
            result = subprocess.run(
                ["taskkill", "/F", "/PID", str(pid), "/T"],
                capture_output=True,
                text=True,
                timeout=5.0
            )
            logger.info("taskkill PID %s: %s", pid, result.stdout.strip())
        except Exception as exc:
            logger.warning("taskkill failed for PID %s: %s", pid, exc)
    
    def _kill_all_webui_processes(self) -> None:
        """
        Kill all WebUI-related processes (used by orphan monitor).
        
        PR-PROCESS-001: Calls _kill_process_tree() which now includes
        CMD/shell wrapper cleanup.
        """
        if self.pid:
            self._kill_process_tree(self.pid)
        else:
            logger.warning("[Orphan Monitor] No WebUI PID tracked, cannot kill processes")

        logger.debug("[Orphan Monitor] Monitor thread exiting")


def discover_webui_port(base_port: int = 7860, max_offset: int = 10) -> int | None:
    """
    Discover which port the WebUI is actually running on.
    
    PR-PORT-DISCOVERY: Scans ports starting from base_port, checking if WebUI
    is responding on any of them. This handles cases where port 7860 is blocked
    and WebUI auto-increments to 7861, 7862, etc.
    
    Args:
        base_port: Starting port to check (default 7860)
        max_offset: Maximum port offset to scan (checks base_port through base_port+max_offset)
    
    Returns:
        Port number where WebUI is responding, or None if not found
    """
    import socket
    from src.api.healthcheck import check_webui_health
    
    logger.info("[PORT-DISCOVERY] Scanning for WebUI on ports %d-%d...", base_port, base_port + max_offset)
    
    for offset in range(max_offset + 1):
        port = base_port + offset
        
        # Quick TCP connection test first
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.5)
                result = sock.connect_ex(('127.0.0.1', port))
                if result != 0:
                    # Port not listening, skip health check
                    continue
        except Exception:
            continue
        
        # Port is listening - verify it's actually WebUI
        test_url = f"http://127.0.0.1:{port}"
        logger.info("[PORT-DISCOVERY] Port %d is listening, testing if it's WebUI...", port)
        
        try:
            if check_webui_health(test_url, timeout=2.0):
                logger.info("[PORT-DISCOVERY] ✓ Found WebUI on port %d", port)
                return port
        except Exception as exc:
            logger.debug("[PORT-DISCOVERY] Port %d health check failed: %s", port, exc)
    
    logger.warning("[PORT-DISCOVERY] WebUI not found on any port in range %d-%d", base_port, base_port + max_offset)
    return None


def kill_orphaned_webui_processes_blocking_port(port: int = 7860, working_dir: str | None = None) -> list[int]:
    """
    Find and kill orphaned WebUI processes that are blocking the specified port.
    
    PR-PORT-DISCOVERY: Identifies processes listening on the port and kills them
    if they appear to be WebUI processes. This handles the case where a previous
    StableNew session crashed and left WebUI running.
    
    Args:
        port: Port to check for blocking processes
        working_dir: Optional WebUI working directory to verify process identity
    
    Returns:
        List of PIDs that were killed
    """
    killed_pids = []
    
    try:
        import psutil
        
        # Find process(es) listening on the port
        for conn in psutil.net_connections(kind='inet'):
            if conn.laddr.port == port and conn.status == 'LISTEN':
                pid = conn.pid
                if pid is None:
                    continue
                
                try:
                    proc = psutil.Process(pid)
                    proc_name = proc.name().lower()
                    cmdline = ' '.join(proc.cmdline()).lower() if proc.cmdline() else ''
                    
                    proc_cwd = None
                    try:
                        proc_cwd = proc.cwd()
                    except Exception:
                        proc_cwd = None

                    python_match = _get_webui_python_match_reasons(
                        process_name=proc.name(),
                        cmdline=proc.cmdline(),
                        cwd=proc_cwd,
                        working_dir=working_dir,
                    )
                    shell_match = _get_webui_shell_match_reasons(
                        process_name=proc.name(),
                        cmdline=proc.cmdline(),
                        cwd=proc_cwd,
                        working_dir=working_dir,
                    )
                    is_webui = bool(python_match or shell_match)
                    
                    if is_webui:
                        logger.warning(
                            "[PORT-DISCOVERY] Found orphaned WebUI process blocking port %d: "
                            "PID=%d, name=%s, cmdline=%s",
                            port, pid, proc.name(), ' '.join(proc.cmdline()[:3]) if proc.cmdline() else 'N/A'
                        )
                        
                        # Kill the process and its children
                        try:
                            # Kill children first
                            children = proc.children(recursive=True)
                            for child in children:
                                try:
                                    child_cmdline = child.cmdline()
                                    try:
                                        child_cwd = child.cwd()
                                    except Exception:
                                        child_cwd = None
                                    child_python_match = _get_webui_python_match_reasons(
                                        process_name=child.name(),
                                        cmdline=child_cmdline,
                                        cwd=child_cwd,
                                        working_dir=working_dir,
                                    )
                                    child_shell_match = _get_webui_shell_match_reasons(
                                        process_name=child.name(),
                                        cmdline=child_cmdline,
                                        cwd=child_cwd,
                                        working_dir=working_dir,
                                    )
                                    if not (child_python_match or child_shell_match):
                                        logger.debug(
                                            "[PORT-DISCOVERY] Skipping unrelated child PID %d (%s)",
                                            child.pid,
                                            child.name(),
                                        )
                                        continue
                                    logger.info("[PORT-DISCOVERY] Killing child PID %d (%s)", child.pid, child.name())
                                    child.kill()
                                    killed_pids.append(child.pid)
                                except Exception as exc:
                                    logger.debug("Failed to kill child %d: %s", child.pid, exc)
                            
                            # Kill parent
                            proc.kill()
                            proc.wait(timeout=3.0)
                            killed_pids.append(pid)
                            logger.info("[PORT-DISCOVERY] ✓ Killed orphaned WebUI PID %d", pid)
                        except psutil.TimeoutExpired:
                            logger.warning("[PORT-DISCOVERY] Process %d did not exit, using taskkill", pid)
                            try:
                                subprocess.run(["taskkill", "/F", "/PID", str(pid), "/T"], 
                                             capture_output=True, timeout=5.0, check=False)
                                killed_pids.append(pid)
                            except Exception:
                                pass
                        except Exception as exc:
                            logger.warning("[PORT-DISCOVERY] Failed to kill PID %d: %s", pid, exc)
                    else:
                        logger.info(
                            "[PORT-DISCOVERY] Process on port %d doesn't look like WebUI: "
                            "PID=%d, name=%s",
                            port, pid, proc.name()
                        )
                
                except psutil.NoSuchProcess:
                    pass
                except Exception as exc:
                    logger.debug("[PORT-DISCOVERY] Error checking process on port %d: %s", port, exc)
    
    except ImportError:
        logger.warning("[PORT-DISCOVERY] psutil not available, cannot check for orphaned processes")
    except Exception as exc:
        logger.error("[PORT-DISCOVERY] Error scanning for orphaned processes: %s", exc)
    
    return killed_pids


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
        from src.utils.config import ConfigManager
    except Exception:
        return None

    launch_profile = app_config.get_webui_launch_profile()

    settings = ConfigManager().load_settings()
    configured_workdir = str(settings.get("webui_workdir") or "").strip()
    configured_base_url = str(settings.get("webui_base_url") or "").strip() or os.environ.get(
        "STABLENEW_WEBUI_BASE_URL", "http://127.0.0.1:7860"
    )
    configured_autostart = bool(settings.get("webui_autostart_enabled", app_config.is_webui_autostart_enabled()))
    configured_timeout = float(
        settings.get("webui_health_total_timeout_seconds")
        or app_config.get_webui_health_total_timeout_seconds()
    )
    if configured_workdir:
        workdir_path = Path(configured_workdir)
        if workdir_path.exists() and workdir_path.is_dir():
            command = list(app_config.resolve_webui_launch_command(launch_profile))
            command_path = workdir_path / command[0]
            if command_path.exists():
                _save_webui_cache(
                    {"workdir": configured_workdir, "command": command, "timestamp": time.time()}
                )
                return WebUIProcessConfig(
                    command=command,
                    working_dir=configured_workdir,
                    launch_profile=launch_profile,
                    startup_timeout_seconds=configured_timeout,
                    autostart_enabled=configured_autostart,
                    base_url=configured_base_url,
                )

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
                logger.debug(f"Using cached WebUI location: {cached_workdir}")
                config = WebUIProcessConfig(
                    command=cached_command,
                    working_dir=cached_workdir,
                    launch_profile=launch_profile,
                    startup_timeout_seconds=configured_timeout,
                    autostart_enabled=configured_autostart,
                    base_url=configured_base_url,
                )
                return config

    # Fall back to app config
    workdir = app_config.get_webui_workdir()
    command = app_config.get_webui_command()

    if workdir and command:
        # Cache this valid configuration
        logger.debug(f"Caching WebUI location: {workdir}")
        _save_webui_cache({"workdir": workdir, "command": command, "timestamp": time.time()})
        return WebUIProcessConfig(
            command=command,
            working_dir=workdir,
            launch_profile=launch_profile,
            startup_timeout_seconds=configured_timeout,
            autostart_enabled=configured_autostart,
            base_url=configured_base_url,
        )

    # Last resort: detect automatically (expensive)
    logger.debug("No cached or configured WebUI location found, performing auto-detection...")
    workdir = detect_default_webui_workdir()
    if workdir:
        workdir_path = Path(workdir)
        # Determine command based on platform
        if os.name == "nt":
            command = list(app_config.resolve_webui_launch_command(launch_profile))
        else:
            command = ["bash", "webui.sh", "--api"]

        # Verify command exists
        command_path = workdir_path / command[0]
        if command_path.exists():
            # Cache the detected configuration
            logger.debug(f"Caching detected WebUI location: {workdir}")
            _save_webui_cache({"workdir": workdir, "command": command, "timestamp": time.time()})
            return WebUIProcessConfig(
                command=command,
                working_dir=workdir,
                launch_profile=launch_profile,
                startup_timeout_seconds=configured_timeout,
                autostart_enabled=configured_autostart,
                base_url=configured_base_url,
            )

    return None


    def _start_orphan_monitor(self) -> None:
        """Start background thread to monitor if GUI is still running."""
        if self._orphan_monitor_thread and self._orphan_monitor_thread.is_alive():
            return
        
        self._orphan_monitor_stop.clear()
        # PR-THREAD-001: Use ThreadRegistry for orphan monitor
        from src.utils.thread_registry import get_thread_registry
        registry = get_thread_registry()
        self._orphan_monitor_thread = registry.spawn(
            target=self._orphan_monitor_loop,
            name="WebUI-Orphan-Monitor",
            daemon=False,
            purpose="Monitor and cleanup orphaned WebUI processes"
        )
        logger.info("[Orphan Monitor] Started monitoring thread to prevent orphaned WebUI processes")

    def _stop_orphan_monitor(self) -> None:
        """Stop the orphan monitor thread."""
        from src.utils.thread_registry import get_thread_registry

        registry = get_thread_registry()
        self._orphan_monitor_stop.set()
        if self._orphan_monitor_thread and self._orphan_monitor_thread.is_alive():
            self._orphan_monitor_thread.join(timeout=2.0)
        if self._orphan_monitor_thread is not None:
            registry.unregister(self._orphan_monitor_thread)
        self._orphan_monitor_thread = None

    def _orphan_monitor_loop(self) -> None:
        """Monitor loop that checks if StableNew GUI is still running."""
        from src.utils.single_instance import SingleInstanceLock
        
        check_interval = 5.0  # Check every 5 seconds
        
        while not self._orphan_monitor_stop.is_set():
            try:
                # Check if GUI is still running
                if not SingleInstanceLock.is_gui_running():
                    logger.error(
                        "[Orphan Monitor] StableNew GUI has exited! "
                        "Terminating WebUI to prevent orphaned process (PID=%s)",
                        self._pid
                    )
                    # Force kill WebUI immediately
                    try:
                        self.stop_webui(grace_seconds=2.0)
                        logger.warning("[Orphan Monitor] WebUI terminated due to GUI exit")
                    except Exception as exc:
                        logger.exception("[Orphan Monitor] Error terminating WebUI: %s", exc)
                    break
                
                # Check if process is still running
                if not self.is_running():
                    logger.debug("[Orphan Monitor] WebUI process has exited naturally, stopping monitor")
                    break
                    
            except Exception as exc:
                logger.exception("[Orphan Monitor] Error in monitor loop: %s", exc)
            
            # Wait for next check or stop signal
            self._orphan_monitor_stop.wait(check_interval)
        
        logger.debug("[Orphan Monitor] Monitor thread exiting")


_GLOBAL_WEBUI_PROCESS_MANAGER: WebUIProcessManager | None = None


def get_global_webui_process_manager() -> WebUIProcessManager | None:
    return _GLOBAL_WEBUI_PROCESS_MANAGER


def clear_global_webui_process_manager() -> None:
    """Clear the global WebUI process manager reference (idempotent)."""
    global _GLOBAL_WEBUI_PROCESS_MANAGER
    _GLOBAL_WEBUI_PROCESS_MANAGER = None
