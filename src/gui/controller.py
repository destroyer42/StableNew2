"""Pipeline controller with cancellation support."""

import logging
import queue
import subprocess
import threading
import time
from collections.abc import Callable
from typing import Any

from .state import CancellationError, CancelToken, GUIState, StateManager

logger = logging.getLogger(__name__)


class LogMessage:
    """Log message with level and timestamp."""

    def __init__(self, message: str, level: str = "INFO"):
        """Initialize log message.

        Args:
            message: Log message text
            level: Log level (INFO, WARNING, ERROR, SUCCESS)
        """
        self.message = message
        self.level = level
        self.timestamp = time.time()


class PipelineController:
    """Controls pipeline execution with cancellation support."""

    @property
    def is_terminal(self):
        return self.state_manager.current in (GUIState.IDLE, GUIState.ERROR)

    _JOIN_TIMEOUT = 5.0

    def __init__(self, state_manager: StateManager):
        self.state_manager = state_manager
        self.cancel_token = CancelToken()
        self.log_queue: queue.Queue[LogMessage] = queue.Queue()

        # Worker + subprocess
        self._worker: threading.Thread | None = None
        self._pipeline = None
        self._current_subprocess: subprocess.Popen | None = None
        self._subprocess_lock = threading.Lock()

        # Cleanup & joining
        self._join_lock = threading.Lock()
        self._cleanup_lock = threading.Lock()
        self._cleanup_started = False  # per-run guard (reset at start of each pipeline run)
        self._cleanup_done = threading.Event()  # signals cleanup completed (per run)
        self._cleanup_done.set()  # no prior run on init; don't block first start

        self._stop_in_progress = False

        # Lifecycle signals
        self.lifecycle_event = threading.Event()  # terminal (IDLE/ERROR)
        self.state_change_event = threading.Event()  # pulse on change

        # Test hook
        self._sync_cleanup = False

        # Epoch
        self._epoch_lock = threading.Lock()
        self._epoch_id = 0

        # Progress callbacks
        self._progress_lock = threading.Lock()
        self._progress_callback: Callable[[float], None] | None = None
        self._eta_callback: Callable[[str], None] | None = None
        self._status_callback: Callable[[str], None] | None = None
        self._last_progress: dict[str, Any] = {
            "stage": "Idle",
            "percent": 0.0,
            "eta": "ETA: --",
        }

    def start_pipeline(
        self,
        pipeline_func: Callable[[], dict[str, Any]],
        on_complete: Callable[[dict[str, Any]], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
    ) -> bool:
        if not self.state_manager.can_run():
            logger.warning("Cannot start pipeline - not in valid state")
            return False
        if not self._cleanup_done.is_set():
            logger.warning("Cannot start pipeline - previous cleanup is still running")
            return False
        if not self.state_manager.transition_to(GUIState.RUNNING):
            return False

        # 2) New epoch
        with self._epoch_lock:
            self._epoch_id += 1
            eid = self._epoch_id
        try:
            self._log(f"[controller] Starting pipeline epoch {eid}", "DEBUG")
        except Exception:
            pass

        # 3) Reset per-run signals
        self._cleanup_started = False
        self.lifecycle_event.clear()
        self.cancel_token.reset()

        def worker():
            error_occurred = False
            try:
                self._log("Pipeline started", "INFO")
                result = pipeline_func()
                if on_complete:
                    on_complete(result)
            except CancellationError:
                self._log("Pipeline cancelled by user", "WARNING")
                self.report_progress("Cancelled", self._last_progress["percent"], "Cancelled")
                try:
                    self.lifecycle_event.set()
                except Exception:
                    logger.debug("Failed to signal lifecycle event on cancellation", exc_info=True)
            except Exception as e:
                error_occurred = True
                self._log(f"Pipeline error: {e}", "ERROR")
                self.state_manager.transition_to(GUIState.ERROR)
                self.report_progress("Error", self._last_progress["percent"], "Error")
                if on_error:
                    on_error(e)
                try:
                    self.lifecycle_event.set()
                except Exception:
                    logger.debug("Failed to signal lifecycle event on error", exc_info=True)

            def cleanup():
                self._do_cleanup(eid, error_occurred)

            if self._sync_cleanup:
                cleanup()
            else:
                threading.Thread(target=cleanup, daemon=True).start()

        self._worker = threading.Thread(target=worker, daemon=True)
        self._worker.start()
        return True

    def stop_pipeline(self) -> bool:
        if not self.state_manager.can_stop():
            logger.warning("Cannot stop pipeline - not running")
            return False

        with self._cleanup_lock:
            if self._stop_in_progress:
                self._log(
                    "Cleanup already in progress; ignoring duplicate stop request", "DEBUG"
                )
                return False
            self._stop_in_progress = True

        self._log("Stop requested - cancelling pipeline...", "WARNING")
        if not self.state_manager.transition_to(GUIState.STOPPING):
            with self._cleanup_lock:
                self._stop_in_progress = False
            return False
        self.cancel_token.cancel()
        self._terminate_subprocess()
        self.report_progress("Cancelled", self._last_progress["percent"], "Cancelled")

        def cleanup():
            with self._epoch_lock:
                eid = self._epoch_id
            self._do_cleanup(eid, error_occurred=False)

        if self._sync_cleanup:
            logger.debug("Sync cleanup requested (tests only); running inline")
            cleanup()
        else:
            threading.Thread(target=cleanup, daemon=True).start()
        return True

    def _do_cleanup(self, eid: int, error_occurred: bool):
        # Ignore stale cleanup from a previous run
        with self._epoch_lock:
            if eid != self._epoch_id:
                return

        with self._cleanup_lock:
            if self._cleanup_started:
                return
            self._cleanup_started = True
            self._cleanup_done.clear()

        try:
            # NEVER join worker thread - violates architecture rule (GUI must not block on threads)
            with self._join_lock:
                self._worker = None

            # Terminate subprocess if still around
            self._terminate_subprocess()

            # State to terminal AFTER teardown
            if not self.state_manager.is_state(GUIState.ERROR):
                self.state_manager.transition_to(GUIState.IDLE)

            # Pulse state change
            self.state_change_event.set()
            self.state_change_event.clear()

            try:
                self._log(
                    f"[controller] Cleanup complete for epoch {eid} (error={error_occurred})",
                    "DEBUG",
                )
            except Exception:
                pass
        finally:
            with self._cleanup_lock:
                self._cleanup_started = False
                self._stop_in_progress = False
            self._cleanup_done.set()
            self.lifecycle_event.set()

        if not error_occurred and not self.cancel_token.is_cancelled():
            self.report_progress("Idle", 0.0, "Idle")

    def set_pipeline(self, pipeline) -> None:
        """Set the pipeline instance to use."""
        self._pipeline = pipeline
        if pipeline and hasattr(pipeline, "set_progress_controller"):
            try:
                pipeline.set_progress_controller(self)
            except TypeError as exc:  # Catch only known failure mode
                logger.debug("Failed to attach progress controller (TypeError): %s", exc)
            except RuntimeError as exc:
                logger.debug("Failed to attach progress controller (RuntimeError): %s", exc)

    def set_progress_callback(self, callback: Callable[[float], None] | None) -> None:
        """Register callback for progress percentage updates."""
        with self._progress_lock:
            self._progress_callback = callback

    def set_eta_callback(self, callback: Callable[[str], None] | None) -> None:
        """Register callback for ETA updates."""
        with self._progress_lock:
            self._eta_callback = callback

    def set_status_callback(self, callback: Callable[[str], None] | None) -> None:
        """Register callback for status/stage text updates."""
        with self._progress_lock:
            self._status_callback = callback

    def report_progress(self, stage: str, percent: float, eta: str | None) -> None:
        """Report progress to registered callbacks in a thread-safe manner."""

        eta_text = eta if eta else "ETA: --"
        try:
            # Suppress non-error updates only after entering ERROR state;
            # allow progress reports while IDLE for unit tests and initialization.
            if self.state_manager.current == GUIState.ERROR and (stage or "").lower() != "error":
                return
        except Exception:
            pass
        with self._progress_lock:
            self._last_progress = {
                "stage": stage,
                "percent": float(percent),
                "eta": eta_text,
            }

            try:
                if self._status_callback:
                    self._status_callback(stage)
            except Exception:
                logger.debug("status_callback raised; ignoring in report_progress", exc_info=True)
            try:
                if self._progress_callback:
                    self._progress_callback(float(percent))
            except Exception:
                logger.debug("progress_callback raised; ignoring in report_progress", exc_info=True)
            try:
                if self._eta_callback:
                    self._eta_callback(eta_text)
            except Exception:
                logger.debug("eta_callback raised; ignoring in report_progress", exc_info=True)

    def _terminate_subprocess(self) -> None:
        """Terminate any running subprocess (e.g., FFmpeg)."""
        with self._subprocess_lock:
            if self._current_subprocess:
                try:
                    self._log("Terminating subprocess...", "INFO")
                    self._current_subprocess.terminate()
                    self._current_subprocess.wait(timeout=3.0)
                    self._log("Subprocess terminated", "INFO")
                except Exception as e:
                    logger.warning(f"Error terminating subprocess: {e}")
                    try:
                        self._current_subprocess.kill()
                    except Exception:
                        pass
                finally:
                    self._current_subprocess = None

    def _cleanup_temp_files(self) -> None:
        """Clean up temporary files created during pipeline execution."""
        # Disabled during test debugging due to fatal Windows exception
        pass

    def register_subprocess(self, process: subprocess.Popen) -> None:
        """Register subprocess for cancellation tracking."""
        with self._subprocess_lock:
            self._current_subprocess = process

    def unregister_subprocess(self) -> None:
        """Unregister subprocess."""
        with self._subprocess_lock:
            self._current_subprocess = None

    def _log(self, message: str, level: str = "INFO") -> None:
        """Add message to log queue."""
        self.log_queue.put(LogMessage(message, level))

    def get_log_messages(self) -> list[LogMessage]:
        """Get all pending log messages."""
        messages = []
        while not self.log_queue.empty():
            try:
                messages.append(self.log_queue.get_nowait())
            except queue.Empty:
                break
        return messages

    def is_running(self) -> bool:
        """Check if pipeline is currently running."""
        return self.state_manager.is_state(GUIState.RUNNING)

    def is_stopping(self) -> bool:
        """Check if pipeline is stopping."""
        return self.state_manager.is_state(GUIState.STOPPING)

    def stop_all(self) -> None:
        """Best-effort shutdown for background workers during teardown."""
        try:
            self.stop_pipeline()
        except Exception:
            pass
        try:
            self.cancel_token.cancel()
        except Exception:
            pass
