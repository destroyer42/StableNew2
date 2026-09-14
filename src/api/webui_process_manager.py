from __future__ import annotations

import json
import logging
import os
import socket
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
        self._owns_process = False
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

    def _teardown_process_container(self, *, terminate_owned: bool) -> None:
        container = self._process_container
        if container is None:
            return
        if terminate_owned:
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

    @property
    def owns_process(self) -> bool:
        """Whether this manager owns the process created by its current launch session."""
        return bool(
            self._owns_process
            and self._process is not None
            and self._pid is not None
            and getattr(self._process, "pid", None) == self._pid
        )

    def _configured_endpoint_is_occupied(self) -> bool:
        """Return whether the explicitly configured endpoint already accepts connections."""
        if not self._config.base_url:
            return False
        try:
            from urllib.parse import urlparse

            parsed = urlparse(self._config.base_url)
            host = parsed.hostname
            port = parsed.port
            if not host or port is None:
                return False
            with socket.create_connection((host, port), timeout=0.2):
                return True
        except OSError:
            return False

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
            logger.warning(
                "[PORT-DISCOVERY] Health check failed on %s, scanning for WebUI on alternate ports...",
                url,
            )
            try:
                discovered_port = discover_webui_port(base_port=7860, max_offset=10)
                if discovered_port and discovered_port != 7860:
                    logger.warning(
                        "[PORT-DISCOVERY] ⚠ Found WebUI on port %d instead of expected 7860. "
                        "This indicates an orphaned process was blocking port 7860. "
                        "Updating base_url to use discovered port.",
                        discovered_port,
                    )
                    # Update the config to use the discovered port
                    self._config.base_url = f"http://127.0.0.1:{discovered_port}"
                    # Try health check again with the correct port
                    return wait_for_webui_ready(
                        self._config.base_url, timeout=5.0, poll_interval=1.0
                    )
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
            if self.owns_process:
                return self._process
            raise WebUIStartupError(
                "A running WebUI process is present without launch-session ownership; "
                "refusing to adopt or replace it"
            )

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
            if self._configured_endpoint_is_occupied():
                raise WebUIStartupError(
                    "Configured WebUI endpoint is already occupied. StableNew will not kill or "
                    "adopt that external process; use the existing external connection or stop it "
                    "explicitly before managed startup."
                )

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

            if self._process_container is None:
                self._init_process_container()
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
            self._owns_process = True
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
            daemon=True,
            purpose="Read WebUI process stdout stream",
            suppress_daemon_warning=True,
        )
        self._stderr_thread = registry.spawn(
            target=_read_stream,
            args=(process.stderr, self._stderr_log_file, self._stderr_tail, "stderr"),
            name="WebUI-stderr-reader",
            daemon=True,
            purpose="Read WebUI process stderr stream",
            suppress_daemon_warning=True,
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
            self._teardown_process_container(terminate_owned=False)
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
        if not self.owns_process:
            logger.info("stop_webui called without an owned WebUI process; no OS action taken")
            return True
        # PR-CORE1-D15: Ensure .terminated attribute exists for test doubles
        if not hasattr(process, "terminated"):
            process.terminated = False
        if process.poll() is not None:
            logger.info("stop_webui called but process already exited")
            self._teardown_process_container(terminate_owned=True)
            self._stop_output_capture()
            self._finalize_process(process)
            # Already exited; terminated remains False
            return True
        pid = getattr(process, "pid", None)
        logger.info("Initiating WebUI shutdown (pid=%s, grace=%.1fs)", pid, grace_seconds)

        owned_descendants = self._owned_descendants(pid)

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
        while elapsed < grace_seconds:
            if process.poll() is not None:
                logger.info("Process %s exited gracefully after %.1fs", pid, elapsed)
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
                logger.warning("Owned process %s did not exit after kill: %s", pid, exc)

            # Last resort: kill entire process tree
            if process.poll() is None:
                self._kill_process_tree(getattr(process, "pid", None))

        self._terminate_owned_descendants(owned_descendants)
        self._teardown_process_container(terminate_owned=True)

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

        if not self.owns_process:
            logger.warning(
                "WebUI restart requested without a manager-owned process; refusing to mutate an "
                "external or ambiguous runtime"
            )
            return False

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
                                "stdout_tail_snippet": exc.stdout_tail[:500]
                                if exc.stdout_tail
                                else "",
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
            self._owns_process = False

    def get_status(self) -> dict[str, Any]:
        return {
            "running": self.is_running(),
            "owns_process": self.owns_process,
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

    def _owned_descendants(self, pid: int | None) -> list[Any]:
        """Snapshot descendants whose ownership is proven by the current parent tree."""
        if not self.owns_process or pid is None or pid != self._pid:
            return []
        try:
            import psutil

            return list(psutil.Process(pid).children(recursive=True))
        except Exception:
            return []

    def _terminate_owned_descendants(self, descendants: list[Any]) -> None:
        for child in reversed(descendants):
            try:
                child.kill()
            except Exception:
                logger.debug("Owned WebUI descendant termination failed", exc_info=True)

    def _kill_process_tree(self, pid: int | None) -> None:
        """Force-stop only the root and descendants owned by this launch session."""
        if not self.owns_process or pid is None or pid != self._pid:
            logger.warning("Refusing process-tree kill without matching WebUI ownership")
            return

        descendants = self._owned_descendants(pid)
        self._terminate_owned_descendants(descendants)
        process = self._process
        if process is not None and process.poll() is None:
            try:
                process.kill()
                process.wait(timeout=2.0)
            except Exception:
                logger.debug("Owned WebUI root termination failed", exc_info=True)

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
        if os.environ.get("STABLENEW_NO_WEBUI") == "1":
            logger.debug("[Orphan Monitor] Skipping monitor startup because STABLENEW_NO_WEBUI=1")
            return

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
            purpose="Monitor and cleanup orphaned WebUI processes",
        )
        logger.info(
            "[Orphan Monitor] Started monitoring thread to prevent orphaned WebUI processes"
        )

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
        """Monitor the owning GUI and stop only this manager's owned process."""
        from src.utils.single_instance import SingleInstanceLock

        gui_pid = os.getpid()
        check_interval = 2.0  # Check every 2 seconds (increased from 5s for faster detection)

        logger.info(
            "[Orphan Monitor] Started: GUI_PID=%s, WebUI_PID=%s, check_interval=%.1fs",
            gui_pid,
            self.pid,
            check_interval,
        )

        while not self._orphan_monitor_stop.is_set():
            try:
                # Check 1: GUI process still alive?
                if not SingleInstanceLock.is_gui_running():
                    logger.error(
                        "[Orphan Monitor] StableNew GUI has exited! "
                        "Terminating WebUI to prevent orphaned process (PID=%s)",
                        self._pid,
                    )
                    self.stop_webui(grace_seconds=2.0)
                    break

                # Check 2: WebUI process still running?
                if not self.is_running():
                    logger.debug(
                        "[Orphan Monitor] WebUI process has exited naturally, stopping monitor"
                    )
                    break

            except Exception as exc:
                logger.exception("[Orphan Monitor] Error in monitor loop: %s", exc)

            # Wait for next check or stop signal
            self._orphan_monitor_stop.wait(check_interval)

        logger.info("[Orphan Monitor] Stopped")

    def cleanup_orphaned_webui_processes(self) -> list[int]:
        """Compatibility no-op: ambiguous orphan processes are never ownership targets."""
        logger.warning(
            "Automatic orphan cleanup is disabled; external or ambiguous WebUI processes "
            "require explicit operator action"
        )
        return []

    def _kill_all_webui_processes(self) -> None:
        """
        Kill all WebUI-related processes (used by orphan monitor).

        PR-PROCESS-001: Calls _kill_process_tree() which now includes
        CMD/shell wrapper cleanup.
        """
        if self.owns_process and self.pid:
            self._kill_process_tree(self.pid)
        else:
            logger.info("[Orphan Monitor] No owned WebUI process; no OS action taken")

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

    logger.info(
        "[PORT-DISCOVERY] Scanning for WebUI on ports %d-%d...", base_port, base_port + max_offset
    )

    for offset in range(max_offset + 1):
        port = base_port + offset

        # Quick TCP connection test first
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.5)
                result = sock.connect_ex(("127.0.0.1", port))
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

    logger.warning(
        "[PORT-DISCOVERY] WebUI not found on any port in range %d-%d",
        base_port,
        base_port + max_offset,
    )
    return None


def kill_orphaned_webui_processes_blocking_port(
    port: int = 7860, working_dir: str | None = None
) -> list[int]:
    """Deprecated non-destructive compatibility shim.

    Port occupancy and working-directory resemblance do not prove StableNew ownership.
    """
    logger.warning(
        "Refusing heuristic WebUI cleanup on port %s (working_dir=%s); explicit ownership required",
        port,
        working_dir,
    )
    return []


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
    configured_autostart = bool(
        settings.get("webui_autostart_enabled", app_config.is_webui_autostart_enabled())
    )
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


_GLOBAL_WEBUI_PROCESS_MANAGER: WebUIProcessManager | None = None


def get_global_webui_process_manager() -> WebUIProcessManager | None:
    return _GLOBAL_WEBUI_PROCESS_MANAGER


def clear_global_webui_process_manager() -> None:
    """Clear the global WebUI process manager reference (idempotent)."""
    global _GLOBAL_WEBUI_PROCESS_MANAGER
    _GLOBAL_WEBUI_PROCESS_MANAGER = None
