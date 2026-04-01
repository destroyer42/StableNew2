from __future__ import annotations

import logging
from typing import Any


class ApplicationRuntimeCoordinator:
    """Own startup/runtime sequencing that should not live in the GUI."""

    def __init__(
        self,
        *,
        job_controller: Any,
        webui_connection_controller: Any,
        logger: logging.Logger | None = None,
    ) -> None:
        self._job_controller = job_controller
        self._webui_connection_controller = webui_connection_controller
        self._logger = logger or logging.getLogger(__name__)
        self._gui_ready = False

    def sync_queue_state(self, *, app_state: Any, job_service: Any) -> None:
        job_controller = self._job_controller
        if job_controller is None:
            return
        if app_state is not None:
            try:
                app_state.set_auto_run_queue(bool(getattr(job_controller, "auto_run_enabled", False)))
                app_state.set_is_queue_paused(bool(getattr(job_controller, "is_queue_paused", False)))
            except Exception:
                pass
        if job_service is not None:
            try:
                job_service.auto_run_enabled = bool(getattr(job_controller, "auto_run_enabled", False))
            except Exception:
                pass

    def on_gui_ready(self) -> None:
        self._gui_ready = True
        self._maybe_trigger_deferred_autostart(reason="gui_ready")

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

