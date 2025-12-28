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
        global _GLOBAL_WEBUI_PROCESS_MANAGER
        _GLOBAL_WEBUI_PROCESS_MANAGER = self

    @property
    def process(self) -> subprocess.Popen | None:
        return self._process

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
            extra_fields={"command": self._config.command, "working_dir": self._config.working_dir},
        )
        run_session_id = build_run_session_id()

        try:
            # For .bat files on Windows, we MUST use shell=True, otherwise they won't execute.
            # Use CREATE_NEW_PROCESS_GROUP to allow clean termination and prevent orphans.
            use_shell = os.name == "nt" and self._config.command[0].endswith(".bat")

            # On Windows, use CREATE_NEW_PROCESS_GROUP + CREATE_BREAKAWAY_FROM_JOB flags
            # This allows us to send CTRL_BREAK_EVENT for clean shutdown.
            creationflags = 0
            if os.name == "nt":
                import subprocess
                # CREATE_NEW_PROCESS_GROUP = 0x00000200
                # CREATE_BREAKAWAY_FROM_JOB = 0x01000000
                creationflags = 0x00000200 | 0x01000000

            self._process = subprocess.Popen(
                self._config.command,
                cwd=self._config.working_dir or None,
                env=self._config.build_env(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=use_shell,
                creationflags=creationflags if os.name == "nt" else 0,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
            self._pid = self._process.pid
            self._start_time = time.time()
            launch_msg = format_launch_message(
                run_session_id=run_session_id,
                pid=self._pid,
                command=self._config.command,
                cwd=self._config.working_dir,
            )
            logger.debug(launch_msg)
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
        for stream in (
            getattr(self._process, "stdout", None),
            getattr(self._process, "stderr", None),
        ):
            try:
                if stream is not None:
                    stream.close()
            except Exception:
                pass
        for thread in (self._stdout_thread, self._stderr_thread):
            if thread and thread.is_alive():
                thread.join(timeout=2.0)
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
        """Kill the process and all WebUI-related python.exe processes."""
        if pid is None:
            logger.warning("_kill_process_tree called with None pid")
            return
        
        logger.info("Forcefully killing WebUI process tree for PID %s", pid)
        
        if platform.system() == "Windows":
            # Kill all python.exe processes that look like WebUI
            try:
                import psutil
                killed_pids = []
                
                # First, try to kill the tracked PID and its children
                try:
                    parent = psutil.Process(pid)
                    children = parent.children(recursive=True)
                    logger.info("Found %d direct child processes for PID %s", len(children), pid)
                    
                    # Kill children first
                    for child in children:
                        try:
                            logger.info("Killing direct child process PID %s (%s)", child.pid, child.name())
                            child.kill()
                            killed_pids.append(child.pid)
                        except psutil.NoSuchProcess:
                            pass
                        except Exception as exc:
                            logger.warning("Failed to kill child PID %s: %s", child.pid, exc)
                    
                    # Kill parent
                    try:
                        parent.kill()
                        logger.info("Killed parent process PID %s", pid)
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
                for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'cwd', 'memory_info']):
                    try:
                        if proc.info['name'] and 'python' in proc.info['name'].lower():
                            cmdline = proc.info.get('cmdline') or []
                            cwd = proc.info.get('cwd', '')
                            mem_info = proc.info.get('memory_info')
                            mem_mb = mem_info.rss / (1024 * 1024) if mem_info else 0
                            all_python_pids.append(proc.pid)
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
                            
                            # Check if this looks like a WebUI process
                            is_webui = False
                            match_reason = []
                            
                            # Check 1: Command line contains webui, launch, or similar
                            cmdline_str = ' '.join(cmdline).lower() if cmdline else ''
                            webui_keywords = ['webui', 'launch.py', 'launch_webui', 'stable-diffusion', 'gradio']
                            for keyword in webui_keywords:
                                if keyword in cmdline_str:
                                    is_webui = True
                                    match_reason.append(f"cmdline contains '{keyword}'")
                                    break
                            
                            # Check 2: Working directory matches our WebUI
                            if webui_dir and cwd:
                                try:
                                    if Path(cwd).resolve() == Path(webui_dir).resolve():
                                        is_webui = True
                                        match_reason.append(f"cwd matches webui_dir")
                                except Exception:
                                    pass
                            
                            # Check 3: FAILSAFE - Memory > 2000MB (likely a leaked WebUI process)
                            # Raised from 500MB to 2000MB to avoid killing legitimate Python processes
                            # WebUI typically uses 4-12GB; this only catches obvious leaks
                            if mem_mb > 2000:
                                is_webui = True
                                match_reason.append(f"memory {mem_mb:.1f} MB > 2000 MB threshold")
                                logger.warning(
                                    "Found large python.exe process PID %s (%.1f MB) - likely WebUI leak",
                                    proc.pid,
                                    mem_mb,
                                )
                            
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
                            was_supposed_to_die = proc.pid in all_python_pids and proc.pid not in killed_pids
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
                        if name and name.lower() in ('cmd.exe', 'conhost.exe'):
                            cmdline = proc.info.get('cmdline', [])
                            cwd = proc.info.get('cwd', '')
                            mem_info = proc.info.get('memory_info')
                            mem_mb = mem_info.rss / (1024 * 1024) if mem_info else 0
                            
                            # Match by working directory
                            is_webui_dir = False
                            if webui_dir and cwd:
                                try:
                                    is_webui_dir = Path(cwd).resolve() == Path(webui_dir).resolve()
                                except Exception:
                                    pass
                            
                            # Match by cmdline mentioning webui or launch
                            is_webui_cmdline = any(
                                'webui' in str(arg).lower() or 
                                'launch' in str(arg).lower()
                                for arg in cmdline
                            )
                            
                            if is_webui_dir or is_webui_cmdline:
                                logger.warning(
                                    ">>> Killing shell process: PID=%s name=%s cwd=%s mem=%.1fMB cmdline=%s",
                                    proc.pid,
                                    name,
                                    cwd[:40] + "..." if len(cwd) > 40 else cwd,
                                    mem_mb,
                                    ' '.join(cmdline[:3]) if cmdline else "N/A"
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
        self._orphan_monitor_stop.set()
        if self._orphan_monitor_thread and self._orphan_monitor_thread.is_alive():
            self._orphan_monitor_thread.join(timeout=2.0)

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
                
                # Is this a WebUI process?
                is_webui = False
                
                # Check by working directory
                if webui_dir and cwd:
                    try:
                        if Path(cwd).resolve() == Path(webui_dir).resolve():
                            is_webui = True
                    except Exception:
                        pass
                
                # Check by cmdline
                if not is_webui:
                    cmdline_str = ' '.join(cmdline).lower() if cmdline else ''
                    webui_keywords = ['webui', 'launch.py', 'launch_webui', 'stable-diffusion', 'gradio']
                    for keyword in webui_keywords:
                        if keyword in cmdline_str:
                            is_webui = True
                            break
                
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
                logger.debug(f"Using cached WebUI location: {cached_workdir}")
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
        logger.debug(f"Caching WebUI location: {workdir}")
        _save_webui_cache({"workdir": workdir, "command": command, "timestamp": time.time()})
        return WebUIProcessConfig(
            command=command,
            working_dir=workdir,
            autostart_enabled=app_config.is_webui_autostart_enabled(),
            base_url=os.environ.get("STABLENEW_WEBUI_BASE_URL", "http://127.0.0.1:7860"),
        )

    # Last resort: detect automatically (expensive)
    logger.debug("No cached or configured WebUI location found, performing auto-detection...")
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
            logger.debug(f"Caching detected WebUI location: {workdir}")
            _save_webui_cache({"workdir": workdir, "command": command, "timestamp": time.time()})
            return WebUIProcessConfig(
                command=command,
                working_dir=workdir,
                autostart_enabled=app_config.is_webui_autostart_enabled(),
                base_url=os.environ.get("STABLENEW_WEBUI_BASE_URL", "http://127.0.0.1:7860"),
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
        self._orphan_monitor_stop.set()
        if self._orphan_monitor_thread and self._orphan_monitor_thread.is_alive():
            self._orphan_monitor_thread.join(timeout=2.0)

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
