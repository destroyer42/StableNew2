from __future__ import annotations

import logging
import socket
import time
from collections.abc import Callable
from enum import Enum
from urllib.parse import urlparse

import psutil
import requests

from src.api.healthcheck import WebUIHealthCheckTimeout, wait_for_webui_ready
from src.api.webui_process_manager import (
    WebUIProcessManager,
    build_default_webui_process_config,
)
from src.config import app_config
from src.utils import LogContext, log_with_ctx

STRICT_READY_CACHE_TTL = 2.5
HEALTH_PROBE_TIMEOUT = (0.25, 1.0)
READINESS_TIMING_WARN_MS = 1000.0


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
        self._base_url_provider = base_url_provider or (
            lambda: app_config._env_default("STABLENEW_WEBUI_BASE_URL", "http://127.0.0.1:7860")
        )
        self._ready_callbacks: list[Callable[[], None]] = list(ready_callbacks or [])
        self._on_resources_updated: Callable[[dict[str, list[object]]], None] | None = None
        self._process_manager: WebUIProcessManager | None = None
        self._process_pid: int | None = None
        self._health_session = requests.Session()
        self._last_strict_check_ts: float | None = None
        self._last_strict_status = False
        self._last_strict_reason: str | None = None
        self._strict_cache_ttl = STRICT_READY_CACHE_TTL
        self._last_connection_timing: dict[str, object] | None = None

    def _record_connection_timing(
        self,
        *,
        base_url: str,
        autostart: bool,
        total_elapsed_ms: float,
        fast_probe_elapsed_ms: float,
        retry_attempts_used: int,
        warmup_requested_ms: float,
        autostart_invoked: bool,
        state: WebUIConnectionState,
        autostart_elapsed_ms: float | None = None,
        autodetect_elapsed_ms: float | None = None,
        detected_url: str | None = None,
        error: str | None = None,
    ) -> None:
        payload: dict[str, object] = {
            "base_url": base_url,
            "autostart": bool(autostart),
            "autostart_invoked": bool(autostart_invoked),
            "state": state.value,
            "total_elapsed_ms": round(float(total_elapsed_ms), 3),
            "fast_probe_elapsed_ms": round(float(fast_probe_elapsed_ms), 3),
            "retry_attempts_used": int(retry_attempts_used),
            "warmup_requested_ms": round(float(warmup_requested_ms), 3),
            "error": error,
        }
        if autostart_elapsed_ms is not None:
            payload["autostart_elapsed_ms"] = round(float(autostart_elapsed_ms), 3)
        if autodetect_elapsed_ms is not None:
            payload["autodetect_elapsed_ms"] = round(float(autodetect_elapsed_ms), 3)
        if detected_url:
            payload["detected_url"] = detected_url
        self._last_connection_timing = payload
        level = (
            logging.WARNING
            if state is WebUIConnectionState.ERROR or total_elapsed_ms >= READINESS_TIMING_WARN_MS
            else logging.INFO
        )
        log_with_ctx(
            self._logger,
            level,
            "WebUI readiness timing",
            ctx=LogContext(subsystem="webui_connection"),
            extra_fields=payload,
        )

    def get_last_connection_timing_snapshot(self) -> dict[str, object] | None:
        if isinstance(self._last_connection_timing, dict):
            return dict(self._last_connection_timing)
        return None

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

    def set_on_resources_updated(
        self, callback: Callable[[dict[str, list[object]]], None] | None
    ) -> None:
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
        overall_started_at = time.monotonic()
        fast_probe_started_at = time.monotonic()
        fast_probe_elapsed_ms = 0.0
        retry_attempts_used = 0
        warmup_requested_ms = 0.0
        autostart_invoked = False
        autostart_elapsed_ms: float | None = None
        autodetect_elapsed_ms: float | None = None
        detected_url: str | None = None
        last_error: str | None = None

        # fast probe
        self._set_state(WebUIConnectionState.CONNECTING)
        try:
            if wait_for_webui_ready(
                base_url, timeout=initial_timeout, poll_interval=retry_interval
            ):
                self._set_state(WebUIConnectionState.READY)
                self._logger.debug("WebUI models/options are ready at %s", base_url)
                self._notify_ready()
                fast_probe_elapsed_ms = (time.monotonic() - fast_probe_started_at) * 1000.0
                self._record_connection_timing(
                    base_url=base_url,
                    autostart=autostart,
                    total_elapsed_ms=(time.monotonic() - overall_started_at) * 1000.0,
                    fast_probe_elapsed_ms=fast_probe_elapsed_ms,
                    retry_attempts_used=retry_attempts_used,
                    warmup_requested_ms=warmup_requested_ms,
                    autostart_invoked=autostart_invoked,
                    state=self._state,
                )
                return self._state
        except Exception as exc:
            last_error = str(exc)
        fast_probe_elapsed_ms = (time.monotonic() - fast_probe_started_at) * 1000.0

        if not autostart or not autostart_enabled:
            self._set_state(WebUIConnectionState.ERROR)
            self._record_connection_timing(
                base_url=base_url,
                autostart=autostart,
                total_elapsed_ms=(time.monotonic() - overall_started_at) * 1000.0,
                fast_probe_elapsed_ms=fast_probe_elapsed_ms,
                retry_attempts_used=retry_attempts_used,
                warmup_requested_ms=warmup_requested_ms,
                autostart_invoked=autostart_invoked,
                state=self._state,
                error=last_error,
            )
            return self._state

        # attempt autostart
        try:
            autostart_invoked = True
            autostart_started_at = time.monotonic()
            proc_cfg = build_default_webui_process_config()
            if proc_cfg is None:
                raise RuntimeError("No WebUI process config available")
            manager = WebUIProcessManager(proc_cfg)
            self._process_manager = manager
            manager.start()
            self._process_pid = manager.pid
            autostart_elapsed_ms = (time.monotonic() - autostart_started_at) * 1000.0
        except Exception as exc:  # pragma: no cover - surface as error state
            self._logger.warning("WebUI autostart failed: %s", exc)
            self._set_state(WebUIConnectionState.ERROR)
            self._record_connection_timing(
                base_url=base_url,
                autostart=autostart,
                total_elapsed_ms=(time.monotonic() - overall_started_at) * 1000.0,
                fast_probe_elapsed_ms=fast_probe_elapsed_ms,
                retry_attempts_used=retry_attempts_used,
                warmup_requested_ms=warmup_requested_ms,
                autostart_invoked=autostart_invoked,
                state=self._state,
                autostart_elapsed_ms=autostart_elapsed_ms,
                error=str(exc),
            )
            return self._state

        # wait a bit before retries
        warmup_requested_ms = min(10.0, total_timeout) * 1000.0
        time.sleep(min(10.0, total_timeout))

        for _ in range(max(retry_count, 0)):
            retry_attempts_used += 1
            try:
                if wait_for_webui_ready(
                    base_url, timeout=retry_interval, poll_interval=retry_interval
                ):
                    self._set_state(WebUIConnectionState.READY)
                    self._logger.debug("WebUI models/options are ready at %s", base_url)
                    self._notify_ready()
                    self._record_connection_timing(
                        base_url=base_url,
                        autostart=autostart,
                        total_elapsed_ms=(time.monotonic() - overall_started_at) * 1000.0,
                        fast_probe_elapsed_ms=fast_probe_elapsed_ms,
                        retry_attempts_used=retry_attempts_used,
                        warmup_requested_ms=warmup_requested_ms,
                        autostart_invoked=autostart_invoked,
                        state=self._state,
                        autostart_elapsed_ms=autostart_elapsed_ms,
                    )
                    return self._state
            except WebUIHealthCheckTimeout as exc:
                last_error = str(exc)
            except Exception as exc:  # pragma: no cover
                last_error = str(exc)
                self._logger.debug("WebUI probe failed: %s", exc)
            time.sleep(retry_interval)

        # If still not ready, try to find WebUI on other ports
        self._logger.info("Trying to auto-detect WebUI on other ports...")
        from src.api.healthcheck import find_webui_port

        autodetect_started_at = time.monotonic()
        detected_url = find_webui_port()
        autodetect_elapsed_ms = (time.monotonic() - autodetect_started_at) * 1000.0
        if detected_url and detected_url != base_url:
            self._logger.info(f"Found WebUI on different port: {detected_url}")
            # Update the base_url_provider to use the detected URL
            self._base_url_provider = lambda: detected_url
            try:
                if wait_for_webui_ready(detected_url, timeout=5.0, poll_interval=1.0):
                    self._set_state(WebUIConnectionState.READY)
                    self._logger.debug("WebUI models/options are ready at %s", detected_url)
                    self._notify_ready()
                    self._record_connection_timing(
                        base_url=base_url,
                        autostart=autostart,
                        total_elapsed_ms=(time.monotonic() - overall_started_at) * 1000.0,
                        fast_probe_elapsed_ms=fast_probe_elapsed_ms,
                        retry_attempts_used=retry_attempts_used,
                        warmup_requested_ms=warmup_requested_ms,
                        autostart_invoked=autostart_invoked,
                        state=self._state,
                        autostart_elapsed_ms=autostart_elapsed_ms,
                        autodetect_elapsed_ms=autodetect_elapsed_ms,
                        detected_url=detected_url,
                    )
                    return self._state
            except Exception as e:
                last_error = str(e)
                self._logger.warning(f"Failed to connect to detected WebUI: {e}")

        self._set_state(WebUIConnectionState.ERROR)
        self._record_connection_timing(
            base_url=base_url,
            autostart=autostart,
            total_elapsed_ms=(time.monotonic() - overall_started_at) * 1000.0,
            fast_probe_elapsed_ms=fast_probe_elapsed_ms,
            retry_attempts_used=retry_attempts_used,
            warmup_requested_ms=warmup_requested_ms,
            autostart_invoked=autostart_invoked,
            state=self._state,
            autostart_elapsed_ms=autostart_elapsed_ms,
            autodetect_elapsed_ms=autodetect_elapsed_ms,
            detected_url=detected_url,
            error=last_error,
        )
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

    def is_process_alive(self) -> bool:
        """Return True if the last-launched WebUI process is still running."""

        pid = self._process_pid
        if pid is None:
            return False
        try:
            alive = psutil.pid_exists(pid)
        except Exception:
            alive = False
        if not alive:
            self._process_pid = None
            self._process_manager = None
        return alive

    def is_port_listening(self, host: str, port: int) -> bool:
        """Probe the configured host/port using a short socket connect."""

        try:
            with socket.create_connection((host, port), timeout=HEALTH_PROBE_TIMEOUT[0]):
                return True
        except OSError:
            return False

    def _extract_host_port(self) -> tuple[str | None, int | None]:
        base_url = self.get_base_url().rstrip("/")
        parsed = urlparse(base_url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        return host, port

    def _probe_endpoint(self, path: str) -> tuple[bool, str | None]:
        response = None
        try:
            url = f"{self.get_base_url().rstrip('/')}{path}"
            response = self._health_session.get(url, timeout=HEALTH_PROBE_TIMEOUT)
            response.raise_for_status()
            return True, None
        except requests.RequestException as exc:
            return False, f"{path} probe failed: {exc}"
        finally:
            if response is not None:
                response.close()

    def _evaluate_strict_readiness(self) -> tuple[bool, str | None]:
        if not self.is_process_alive():
            return False, "process not alive"
        host, port = self._extract_host_port()
        if not host or port is None:
            return False, "invalid base URL"
        if not self.is_port_listening(host, port):
            return False, f"port {host}:{port} not listening"
        for endpoint in ("/sdapi/v1/options", "/sdapi/v1/sd-models"):
            ok, reason = self._probe_endpoint(endpoint)
            if not ok:
                return False, reason
        return True, None

    def is_webui_ready_strict(self) -> bool:
        """Return True only if process alive, port listening, and API probes succeed."""

        now = time.monotonic()
        if self._last_strict_check_ts and now - self._last_strict_check_ts < self._strict_cache_ttl:
            return self._last_strict_status
        ready, reason = self._evaluate_strict_readiness()
        self._last_strict_status = ready
        self._last_strict_reason = reason
        self._last_strict_check_ts = now
        if not ready:
            self._logger.debug("Strict readiness check failed: %s", reason)
        return ready

    @property
    def last_readiness_error(self) -> str | None:
        """Expose the most recent strict readiness failure reason."""

        return self._last_strict_reason


__all__ = ["WebUIConnectionController", "WebUIConnectionState"]
