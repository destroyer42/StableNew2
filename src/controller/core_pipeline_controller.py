"""Controller-owned base pipeline controller.

This module owns lifecycle, cancellation, and progress plumbing that used to
live under src.gui. It is safe for controller/pipeline runtime code to depend on.
"""

from __future__ import annotations

import logging
import queue
import subprocess
import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from src.controller.runtime_state import (
    CancelToken,
    GUIState,
    PipelineState,
    StateManager,
)

if TYPE_CHECKING:
    from src.gui.prompt_workspace_state import PromptWorkspaceState

logger = logging.getLogger(__name__)


class LogMessage:
    """Log message with level and timestamp."""

    def __init__(self, message: str, level: str = "INFO"):
        self.message = message
        self.level = level
        self.timestamp = time.time()


class CorePipelineController:
    """Controller-owned lifecycle and progress base for pipeline controllers."""

    @property
    def is_terminal(self):
        return self.state_manager.current in (GUIState.IDLE, GUIState.ERROR)

    _JOIN_TIMEOUT = 5.0

    def __init__(self, state_manager: StateManager | None = None, app_controller: Any | None = None):
        self.state_manager = state_manager or StateManager()
        self.cancel_token = CancelToken()
        self.log_queue: queue.Queue[LogMessage] = queue.Queue()
        self._app_controller = app_controller
        self._worker: threading.Thread | None = None
        self._pipeline = None
        self._current_subprocess: subprocess.Popen | None = None
        self._subprocess_lock = threading.Lock()
        self._join_lock = threading.Lock()
        self._cleanup_lock = threading.Lock()
        self._cleanup_started = False
        self._cleanup_done = threading.Event()
        self._cleanup_done.set()
        self._stop_in_progress = False
        self.lifecycle_event = threading.Event()
        self.state_change_event = threading.Event()
        self._sync_cleanup = False
        self._epoch_lock = threading.Lock()
        self._epoch_id = 0
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
        *,
        run_config: dict[str, Any] | None = None,
        on_complete: Callable[[dict[str, Any]], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
    ) -> bool:
        logger.error(
            "Base pipeline controller start_pipeline no longer supports direct callable execution; "
            "use the NJR-backed controller implementation with run_config."
        )
        if on_error is not None:
            on_error(RuntimeError("Direct callable pipeline execution is retired in v2.6"))
        return False

    def stop_pipeline(self) -> bool:
        if not self.state_manager.can_stop():
            logger.warning("Cannot stop pipeline - not running")
            return False

        with self._cleanup_lock:
            if self._stop_in_progress:
                self._log("Cleanup already in progress; ignoring duplicate stop request", "DEBUG")
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
            from src.utils.thread_registry import get_thread_registry

            registry = get_thread_registry()
            registry.spawn(
                target=cleanup,
                name="Controller-Stop-Cleanup",
                daemon=False,
                purpose="Cleanup after stopping pipeline controller",
            )
        return True

    def _do_cleanup(self, eid: int, error_occurred: bool):
        with self._epoch_lock:
            if eid != self._epoch_id:
                return

        with self._cleanup_lock:
            if self._cleanup_started:
                return
            self._cleanup_started = True
            self._cleanup_done.clear()

        try:
            with self._join_lock:
                self._worker = None

            self._terminate_subprocess()

            if not self.state_manager.is_state(GUIState.ERROR):
                self.state_manager.transition_to(GUIState.IDLE)

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
        self._pipeline = pipeline
        if pipeline and hasattr(pipeline, "set_progress_controller"):
            try:
                pipeline.set_progress_controller(self)
            except TypeError as exc:
                logger.debug("Failed to attach progress controller (TypeError): %s", exc)
            except RuntimeError as exc:
                logger.debug("Failed to attach progress controller (RuntimeError): %s", exc)

    def set_progress_callback(self, callback: Callable[[float], None] | None) -> None:
        with self._progress_lock:
            self._progress_callback = callback

    def set_eta_callback(self, callback: Callable[[str], None] | None) -> None:
        with self._progress_lock:
            self._eta_callback = callback

    def set_status_callback(self, callback: Callable[[str], None] | None) -> None:
        with self._progress_lock:
            self._status_callback = callback

    def report_progress(self, stage: str, percent: float, eta: str | None) -> None:
        if self._app_controller is not None:
            try:
                self._app_controller.last_ui_heartbeat_ts = time.monotonic()
            except Exception:
                pass

        eta_text = eta if eta else "ETA: --"
        try:
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
        with self._subprocess_lock:
            if self._current_subprocess:
                try:
                    self._log("Terminating subprocess...", "INFO")
                    self._current_subprocess.terminate()
                    self._current_subprocess.wait(timeout=3.0)
                    self._log("Subprocess terminated", "INFO")
                except Exception as exc:
                    logger.warning("Error terminating subprocess: %s", exc)
                    try:
                        self._current_subprocess.kill()
                    except Exception:
                        pass
                finally:
                    self._current_subprocess = None

    def _cleanup_temp_files(self) -> None:
        pass

    def register_subprocess(self, process: subprocess.Popen) -> None:
        with self._subprocess_lock:
            self._current_subprocess = process

    def unregister_subprocess(self) -> None:
        with self._subprocess_lock:
            self._current_subprocess = None

    def _log(self, message: str, level: str = "INFO") -> None:
        self.log_queue.put(LogMessage(message, level))

    def get_log_messages(self) -> list[LogMessage]:
        messages = []
        while not self.log_queue.empty():
            try:
                messages.append(self.log_queue.get_nowait())
            except queue.Empty:
                break
        return messages

    def is_running(self) -> bool:
        return self.state_manager.is_state(GUIState.RUNNING)

    def is_stopping(self) -> bool:
        return self.state_manager.is_state(GUIState.STOPPING)

    def stop_all(self) -> None:
        try:
            self.stop_pipeline()
        except Exception:
            pass
        try:
            self.cancel_token.cancel()
        except Exception:
            pass

    def gui_can_run(self) -> bool:
        return self.state_manager.can_run()

    def gui_can_stop(self) -> bool:
        return self.state_manager.can_stop()

    def gui_transition_state(self, new_state: GUIState) -> bool:
        return self.state_manager.transition_to(new_state)

    def gui_get_pipeline_state(self) -> PipelineState | None:
        return getattr(self.state_manager, "pipeline_state", None)

    def gui_set_pipeline_run_mode(self, mode: str) -> None:
        pipeline_state = self.gui_get_pipeline_state()
        if pipeline_state is not None:
            try:
                pipeline_state.run_mode = mode
            except Exception:
                pass

    def gui_get_pipeline_overrides(self) -> dict[str, object]:
        extractor = getattr(self.state_manager, "get_pipeline_overrides", None)
        overrides: dict[str, object] | None = None
        if callable(extractor):
            try:
                overrides = extractor()
            except Exception:
                overrides = None
        if isinstance(overrides, dict) and overrides:
            return dict(overrides)
        stored = getattr(self.state_manager, "pipeline_overrides", None)
        if isinstance(stored, dict):
            return dict(stored)
        return {}

    def gui_get_metadata(self, attr_name: str) -> dict[str, Any] | None:
        accessor = getattr(self.state_manager, attr_name, None)
        value: Any = None
        if callable(accessor):
            try:
                value = accessor()
            except Exception:
                return None
        else:
            value = accessor
        if isinstance(value, dict):
            return dict(value)
        return None

    def gui_get_prompt_workspace_state(self) -> PromptWorkspaceState | None:
        return getattr(self.state_manager, "prompt_workspace_state", None)
