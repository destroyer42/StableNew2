from __future__ import annotations

import logging
import socket
import threading
import time
from collections.abc import Callable
from enum import Enum
from urllib.parse import urlparse

import psutil
import requests

from src.api.healthcheck import clear_readiness_failure_state, wait_for_webui_ready
from src.api.webui_process_manager import (
    WebUIProcessManager,
    WebUIReadyEvent,
    active_owned_webui_process_manager,
    build_default_webui_process_config,
    wait_for_managed_startup,
)
from src.api.webui_runtime_identity import effective_webui_base_url
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
        self._base_url_provider = base_url_provider or effective_webui_base_url
        self._ready_callbacks: list[Callable[[], None]] = list(ready_callbacks or [])
        self._on_resources_updated: Callable[[dict[str, list[object]]], None] | None = None
        self._process_manager: WebUIProcessManager | None = None
        self._process_pid: int | None = None
        self._ready_epoch = 0
        # One connection attempt at a time: Launch, Retry, auto-reconnect and run preflight all converge here.
        self._flight = threading.Lock()
        self._flight_owner: int | None = None
        # Makes "publish ERROR unless READY" atomic against a manager thread publishing READY.
        self._state_lock = threading.Lock()
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
        with self._state_lock:
            self._state = state

    @property
    def ready_epoch(self) -> int:
        """Incremented every time READY is announced (connect, startup proof or owned-restart recovery)."""
        return self._ready_epoch

    def attach_process_manager(self, manager: WebUIProcessManager) -> None:
        """Observe the one active manager: its proven readiness epochs become READY events here."""

        previous = self._process_manager
        if previous is manager:
            return
        remove = getattr(previous, "remove_ready_listener", None)
        if callable(remove):
            remove(self._on_manager_ready)
        self._process_manager = manager
        add = getattr(manager, "add_ready_listener", None)
        if callable(add):
            add(self._on_manager_ready)

    def _on_manager_ready(self, event: WebUIReadyEvent) -> None:
        """A startup/restart proof from the owning manager: follow its PID, drop the stale verdict, announce READY."""

        self._process_pid = event.pid
        self._last_strict_check_ts = None
        self._set_state(WebUIConnectionState.READY)
        self._notify_ready()

    def _notify_ready(self) -> None:
        self._ready_epoch += 1
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
        """Connect to the one configured endpoint (single-flight).

        The configured runtime endpoint is authoritative: no other port is probed or adopted, and a caller that
        arrives while an attempt is in flight joins it and reports its outcome instead of starting a competing one.
        """

        if not self._flight.acquire(blocking=False):
            if self._flight_owner == threading.get_ident():
                # A ready callback re-entering from the attempt's own thread: blocking on its own lock would deadlock.
                return self._state
            self._logger.info("WebUI connection attempt already in flight; joining it")
            with self._flight:
                return self._state
        self._flight_owner = threading.get_ident()
        try:
            return self._connect(autostart)
        finally:
            self._flight_owner = None
            self._flight.release()

    @staticmethod
    def _startup_budget(manager: object, fallback: float) -> float:
        value = getattr(manager, "startup_timeout_seconds", None)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            return float(value)
        return max(float(fallback), 1.0)

    def _settle_error(self, start_epoch: int, base_url: str, error: str | None) -> None:
        """Publish ERROR unless another path proved the runtime READY while this attempt ran.

        This attempt set CONNECTING itself and only publishes READY on its own success paths, so READY here is always
        a newer proof from the owning manager (which may publish the state just before its epoch is announced).
        """

        with self._state_lock:
            stale = self._state is WebUIConnectionState.READY
            if not stale:
                self._state = WebUIConnectionState.ERROR
        if stale:
            log_with_ctx(
                self._logger,
                logging.INFO,
                "Stale WebUI connection failure ignored; a newer readiness proof exists",
                ctx=LogContext(subsystem="webui_connection"),
                extra_fields={
                    "event": "webui_stale_failure_ignored",
                    "configured_endpoint": base_url,
                    "ready_epoch": self._ready_epoch,
                    "start_epoch": start_epoch,
                    "error": error,
                },
            )

    def _connect(self, autostart: bool) -> WebUIConnectionState:
        base_url = self._base_url_provider()
        initial_timeout = app_config.get_webui_health_initial_timeout_seconds()
        retry_interval = app_config.get_webui_health_retry_interval_seconds()
        total_timeout = app_config.get_webui_health_total_timeout_seconds()
        autostart_enabled = app_config.get_webui_autostart_enabled()
        overall_started_at = time.monotonic()
        fast_probe_started_at = time.monotonic()
        fast_probe_elapsed_ms = 0.0
        start_epoch = self._ready_epoch
        autostart_invoked = False
        autostart_elapsed_ms: float | None = None
        last_error: str | None = None

        def record(error: str | None = None) -> None:
            self._record_connection_timing(
                base_url=base_url,
                autostart=autostart,
                total_elapsed_ms=(time.monotonic() - overall_started_at) * 1000.0,
                fast_probe_elapsed_ms=fast_probe_elapsed_ms,
                retry_attempts_used=0,
                warmup_requested_ms=0.0,
                autostart_invoked=autostart_invoked,
                state=self._state,
                autostart_elapsed_ms=autostart_elapsed_ms,
                error=error,
            )

        # An explicit connection attempt overrides passive probe backoff left by earlier refused connections, so a
        # runtime that came up since then is not reported unavailable by a stale cooldown.
        clear_readiness_failure_state(base_url)
        self._set_state(WebUIConnectionState.CONNECTING)
        try:
            if wait_for_webui_ready(base_url, timeout=initial_timeout, poll_interval=retry_interval):
                self._set_state(WebUIConnectionState.READY)
                self._logger.debug("WebUI models/options are ready at %s", base_url)
                self._notify_ready()
                fast_probe_elapsed_ms = (time.monotonic() - fast_probe_started_at) * 1000.0
                record()
                return self._state
        except Exception as exc:
            last_error = str(exc)
        fast_probe_elapsed_ms = (time.monotonic() - fast_probe_started_at) * 1000.0

        if not autostart or not autostart_enabled:
            self._settle_error(start_epoch, base_url, last_error)
            record(last_error)
            return self._state

        # Managed startup on the one owned manager; its bounded, slice-cleaned wait publishes readiness.
        try:
            autostart_invoked = True
            autostart_started_at = time.monotonic()
            manager = self._process_manager or active_owned_webui_process_manager()
            if manager is None:
                proc_cfg = build_default_webui_process_config()
                if proc_cfg is None:
                    raise RuntimeError("No WebUI process config available")
                manager = WebUIProcessManager(proc_cfg)
            self.attach_process_manager(manager)
            manager.start()
            self._process_pid = manager.pid
            autostart_elapsed_ms = (time.monotonic() - autostart_started_at) * 1000.0
        except Exception as exc:  # pragma: no cover - surface as error state
            self._logger.warning("WebUI autostart failed: %s", exc)
            self._settle_error(start_epoch, base_url, str(exc))
            record(str(exc))
            return self._state

        epoch_before_wait = self._ready_epoch
        try:
            wait_for_managed_startup(
                manager,
                base_url,
                timeout_s=self._startup_budget(manager, total_timeout),
                probe=wait_for_webui_ready,
            )
            if self._ready_epoch == epoch_before_wait:
                # The manager's listener did not announce it (for example an unattached test double).
                self._set_state(WebUIConnectionState.READY)
                self._notify_ready()
            self._logger.debug("WebUI models/options are ready at %s", base_url)
            record()
            return self._state
        except Exception as exc:
            last_error = str(exc)
            self._logger.warning("WebUI did not become ready at its configured endpoint: %s", exc)

        log_with_ctx(
            self._logger,
            logging.INFO,
            "WebUI connection failed; alternate-port discovery is not performed",
            ctx=LogContext(subsystem="webui_connection"),
            extra_fields={
                "event": "webui_port_discovery_refused",
                "configured_endpoint": base_url,
                "owned_pid": self._process_pid if isinstance(self._process_pid, int) else None,
            },
        )
        self._settle_error(start_epoch, base_url, last_error)
        record(last_error)
        return self._state

    def get_base_url(self) -> str:
        """Return the current base URL used for WebUI health checks."""
        return self._base_url_provider()

    def set_base_url(self, url: str) -> None:
        """Manually set the base URL for WebUI connection."""
        self._base_url_provider = lambda: url
        self._logger.info(f"WebUI base URL manually set to: {url}")

    def reconnect(self) -> WebUIConnectionState:
        """Best-effort reconnect helper used by GUI retry buttons (joins an attempt already in flight)."""
        if self._flight.locked():  # in flight (possibly this thread, via a callback): join it, never reset state
            return self.ensure_connected(autostart=True)
        self._set_state(WebUIConnectionState.DISCONNECTED)
        try:
            return self.ensure_connected(autostart=True)
        except Exception as exc:  # pragma: no cover - propagated to GUI
            self._logger.warning("WebUI reconnect failed: %s", exc)
            self._set_state(WebUIConnectionState.ERROR)
            return self._state

    def is_process_alive(self) -> bool:
        """Return True if the last WebUI process owned by StableNew is running.

        A ``None`` PID means the configured WebUI is externally managed.  A
        known PID that has exited remains recorded as an ownership marker so
        strict readiness cannot silently accept an unrelated process on the
        same port.
        """

        pid = self._process_pid
        if pid is None:
            return False
        try:
            return psutil.pid_exists(pid)
        except Exception:
            return False

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
        if self._process_pid is not None and not self.is_process_alive():
            return False, "owned process not alive"
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
