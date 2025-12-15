from __future__ import annotations

import logging
import time
from enum import Enum
from typing import Callable

from src.api.healthcheck import wait_for_webui_ready, WebUIHealthCheckTimeout
from src.api.webui_process_manager import WebUIProcessConfig, WebUIProcessManager, build_default_webui_process_config
from src.config import app_config


class WebUIConnectionState(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    READY = "ready"
    ERROR = "error"
    DISABLED = "disabled"


class WebUIConnectionController:
    """Encapsulates WebUI connection workflow and state."""

    def __init__(
        self,
        *,
        logger: logging.Logger | None = None,
        base_url_provider: Callable[[], str] | None = None,
        ready_callbacks: list[Callable[[], None]] | None = None,
    ) -> None:
        self._state = WebUIConnectionState.DISCONNECTED
        self._logger = logger or logging.getLogger(__name__)
        self._base_url_provider = base_url_provider or (lambda: app_config._env_default("STABLENEW_WEBUI_BASE_URL", "http://127.0.0.1:7860"))
        self._ready_callbacks: list[Callable[[], None]] = list(ready_callbacks or [])
        self._on_resources_updated: Callable[[dict[str, list[object]]], None] | None = None

    def get_state(self) -> WebUIConnectionState:
        return self._state

    def _set_state(self, state: WebUIConnectionState) -> None:
        self._state = state

    def _notify_ready(self) -> None:
        callbacks = list(self._ready_callbacks)
        for callback in callbacks:
            try:
                callback()
            except Exception as exc:
                self._logger.debug("WebUI ready callback failed: %s", exc)

    def set_on_resources_updated(self, callback: Callable[[dict[str, list[object]]], None] | None) -> None:
        """Register a single callback invoked when resources are refreshed."""
        self._on_resources_updated = callback

    def notify_resources_updated(self, resources: dict[str, list[object]] | None) -> None:
        """Invoke the registered resources callback when a refresh completes."""
        if self._on_resources_updated is None or resources is None:
            return
        try:
            self._on_resources_updated(resources)
        except Exception as exc:
            self._logger.debug("WebUI resources callback failed: %s", exc)

    def register_on_ready(self, callback: Callable[[], None]) -> None:
        if callback in self._ready_callbacks:
            return
        self._ready_callbacks.append(callback)

    def ensure_connected(self, autostart: bool = True) -> WebUIConnectionState:
        base_url = self._base_url_provider()
        initial_timeout = app_config.get_webui_health_initial_timeout_seconds()
        retry_count = app_config.get_webui_health_retry_count()
        retry_interval = app_config.get_webui_health_retry_interval_seconds()
        total_timeout = app_config.get_webui_health_total_timeout_seconds()
        autostart_enabled = app_config.get_webui_autostart_enabled()

        # fast probe
        self._set_state(WebUIConnectionState.CONNECTING)
        try:
            if wait_for_webui_ready(base_url, timeout=initial_timeout, poll_interval=retry_interval):
                self._set_state(WebUIConnectionState.READY)
                self._logger.info("WebUI models/options are ready at %s", base_url)
                self._notify_ready()
                return self._state
        except Exception:
            pass

        if not autostart or not autostart_enabled:
            self._set_state(WebUIConnectionState.ERROR)
            return self._state

        # attempt autostart
        try:
            proc_cfg = build_default_webui_process_config()
            if proc_cfg is None:
                raise RuntimeError("No WebUI process config available")
            WebUIProcessManager(proc_cfg).start()
        except Exception as exc:  # pragma: no cover - surface as error state
            self._logger.warning("WebUI autostart failed: %s", exc)
            self._set_state(WebUIConnectionState.ERROR)
            return self._state

        # wait a bit before retries
        time.sleep(min(10.0, total_timeout))

        for _ in range(max(retry_count, 0)):
            try:
                if wait_for_webui_ready(base_url, timeout=retry_interval, poll_interval=retry_interval):
                    self._set_state(WebUIConnectionState.READY)
                    self._logger.info("WebUI models/options are ready at %s", base_url)
                    self._notify_ready()
                    return self._state
            except WebUIHealthCheckTimeout:
                pass
            except Exception as exc:  # pragma: no cover
                self._logger.debug("WebUI probe failed: %s", exc)
            time.sleep(retry_interval)

        # If still not ready, try to find WebUI on other ports
        self._logger.info("Trying to auto-detect WebUI on other ports...")
        from src.api.healthcheck import find_webui_port
        detected_url = find_webui_port()
        if detected_url and detected_url != base_url:
            self._logger.info(f"Found WebUI on different port: {detected_url}")
            # Update the base_url_provider to use the detected URL
            self._base_url_provider = lambda: detected_url
            try:
                if wait_for_webui_ready(detected_url, timeout=5.0, poll_interval=1.0):
                    self._set_state(WebUIConnectionState.READY)
                    self._logger.info("WebUI models/options are ready at %s", detected_url)
                    self._notify_ready()
                    return self._state
            except Exception as e:
                self._logger.warning(f"Failed to connect to detected WebUI: {e}")

        self._set_state(WebUIConnectionState.ERROR)
        return self._state

    def get_base_url(self) -> str:
        """Return the current base URL used for WebUI health checks."""
        return self._base_url_provider()
    def set_base_url(self, url: str) -> None:
        """Manually set the base URL for WebUI connection."""
        self._base_url_provider = lambda: url
        self._logger.info(f"WebUI base URL manually set to: {url}")

    def reconnect(self) -> WebUIConnectionState:
        """Best-effort reconnect helper used by GUI retry buttons."""
        self._set_state(WebUIConnectionState.DISCONNECTED)
        try:
            return self.ensure_connected(autostart=True)
        except Exception as exc:  # pragma: no cover - propagated to GUI
            self._logger.warning("WebUI reconnect failed: %s", exc)
            self._set_state(WebUIConnectionState.ERROR)
            return self._state


__all__ = ["WebUIConnectionController", "WebUIConnectionState"]
