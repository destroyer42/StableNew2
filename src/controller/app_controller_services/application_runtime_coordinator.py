"""Coordinate GUI and WebUI readiness, queue projection, and deferred queue autostart."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from src.utils.thread_registry import get_thread_registry


class ApplicationRuntimeCoordinator:
    """Own startup/runtime sequencing that should not live in the GUI."""

    def __init__(
        self,
        *,
        job_controller: Any,
        webui_connection_controller: Any,
        logger: logging.Logger | None = None,
        spawn: Callable[[Callable[[], None]], None] | None = None,
    ) -> None:
        self._job_controller = job_controller
        self._webui_connection_controller = webui_connection_controller
        self._logger = logger or logging.getLogger(__name__)
        self._gui_ready = False
        self._spawn = spawn or self._spawn_tracked

    def sync_queue_state(self, *, app_state: Any, job_service: Any) -> None:
        job_controller = self._job_controller
        if job_controller is None:
            return
        if app_state is not None:
            try:
                app_state.set_auto_run_queue(
                    bool(getattr(job_controller, "auto_run_enabled", False))
                )
                app_state.set_is_queue_paused(
                    bool(getattr(job_controller, "is_queue_paused", False))
                )
            except Exception:
                pass
        if job_service is not None:
            try:
                job_service.auto_run_enabled = bool(
                    getattr(job_controller, "auto_run_enabled", False)
                )
            except Exception:
                pass

    def on_gui_ready(self) -> None:
        """Called on the Tk thread; the strict readiness check does network I/O, so it runs on a worker."""
        self._gui_ready = True
        self._spawn(lambda: self._maybe_trigger_deferred_autostart(reason="gui_ready"))

    def _spawn_tracked(self, work: Callable[[], None]) -> None:
        try:
            get_thread_registry().spawn(
                target=work,
                name="DeferredAutostart",
                purpose="Check WebUI readiness off the UI thread before deferred queue autostart",
            )
        except RuntimeError:  # the app is closing; nothing left to start
            self._logger.debug("Deferred autostart skipped: the app is shutting down")

    def on_webui_ready(self) -> None:
        self._maybe_trigger_deferred_autostart(reason="webui_ready")

    def _maybe_trigger_deferred_autostart(self, *, reason: str) -> None:
        if not self._gui_ready:
            self._logger.debug("Skipping deferred autostart before GUI ready (reason=%s)", reason)
            return
        controller = self._webui_connection_controller
        is_ready = getattr(controller, "is_webui_ready_strict", None)
        if callable(is_ready):
            try:
                if not is_ready():
                    self._logger.info(
                        "[STARTUP-PERF] WebUI not strictly ready yet; deferring queue autostart (%s)",
                        reason,
                    )
                    return
            except Exception:
                pass
        trigger = getattr(self._job_controller, "trigger_deferred_autostart", None)
        if callable(trigger):
            try:
                self._logger.info("[STARTUP-PERF] Triggering deferred queue autostart (%s)", reason)
                trigger()
            except Exception:
                self._logger.exception("Deferred queue autostart failed", exc_info=True)
