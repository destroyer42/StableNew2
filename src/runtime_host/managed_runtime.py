from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable
from typing import Any

from src.api.healthcheck import wait_for_webui_ready
from src.api.webui_process_manager import (
    WebUIProcessConfig,
    WebUIProcessManager,
    build_default_webui_process_config,
)
from src.video.comfy_healthcheck import wait_for_comfy_ready
from src.video.comfy_process_manager import (
    ComfyProcessConfig,
    ComfyProcessManager,
    build_default_comfy_process_config,
)


BACKGROUND_STARTUP_PROBE_TIMEOUT_SECONDS = 10.0
BACKGROUND_STARTUP_PROBE_POLL_INTERVAL_SECONDS = 1.0


def load_webui_config(
    *,
    build_process_config: Callable[[], Any | None] = build_default_webui_process_config,
    getenv: Callable[[str, str | None], str | None] = os.getenv,
) -> dict[str, Any]:
    cfg = {
        "webui_base_url": getenv("STABLENEW_WEBUI_BASE_URL", "http://127.0.0.1:7860"),
    }

    proc_config = build_process_config()
    if proc_config:
        env_override_cmd = str(getenv("STABLENEW_WEBUI_COMMAND", "") or "").split()
        if env_override_cmd:
            proc_config.command = env_override_cmd
        workdir_override = getenv("STABLENEW_WEBUI_WORKDIR", None)
        if workdir_override:
            proc_config.working_dir = workdir_override
        autostart_env = getenv("STABLENEW_WEBUI_AUTOSTART", None)
        if autostart_env is not None:
            proc_config.autostart_enabled = autostart_env.lower() in {"1", "true", "yes"}
        timeout_override = getenv("STABLENEW_WEBUI_TIMEOUT", None)
        if timeout_override:
            try:
                proc_config.startup_timeout_seconds = float(timeout_override)
            except Exception:
                pass
        cfg["webui_base_url"] = str(
            proc_config.base_url or cfg.get("webui_base_url") or "http://127.0.0.1:7860"
        )
        cfg["process_config"] = proc_config
    return cfg


def load_comfy_config(
    *,
    build_process_config: Callable[[], Any | None] = build_default_comfy_process_config,
    getenv: Callable[[str, str | None], str | None] = os.getenv,
) -> dict[str, Any]:
    cfg = {
        "comfy_base_url": getenv("STABLENEW_COMFY_BASE_URL", "http://127.0.0.1:8188"),
    }

    proc_config = build_process_config()
    if proc_config:
        env_override_cmd = str(getenv("STABLENEW_COMFY_COMMAND", "") or "").split()
        if env_override_cmd:
            proc_config.command = env_override_cmd
        workdir_override = getenv("STABLENEW_COMFY_WORKDIR", None)
        if workdir_override:
            proc_config.working_dir = workdir_override
        autostart_env = getenv("STABLENEW_COMFY_AUTOSTART", None)
        if autostart_env is not None:
            proc_config.autostart_enabled = autostart_env.lower() in {"1", "true", "yes"}
        timeout_override = getenv("STABLENEW_COMFY_TIMEOUT", None)
        if timeout_override:
            try:
                proc_config.startup_timeout_seconds = float(timeout_override)
            except Exception:
                pass
        cfg["comfy_base_url"] = str(
            proc_config.base_url or cfg.get("comfy_base_url") or "http://127.0.0.1:8188"
        )
        cfg["process_config"] = proc_config
    return cfg


def bootstrap_webui(
    config: dict[str, Any],
    *,
    process_manager_cls: type[WebUIProcessManager] = WebUIProcessManager,
    wait_ready_fn: Callable[..., bool] = wait_for_webui_ready,
    logger_module: Any = logging,
) -> WebUIProcessManager | None:
    proc_config = config.get("process_config")
    if proc_config is None and config.get("webui_command"):
        proc_config = WebUIProcessConfig(
            command=list(config.get("webui_command") or []),
            working_dir=config.get("webui_workdir"),
            startup_timeout_seconds=float(config.get("webui_startup_timeout_seconds") or 60.0),
            autostart_enabled=bool(config.get("webui_autostart_enabled")),
            base_url=config.get("webui_base_url"),
        )
    if proc_config is None:
        logger_module.info("No WebUI configuration available")
        base_url = config.get("webui_base_url")
        if base_url:
            wait_ready_fn(base_url)
        return None

    manager = process_manager_cls(proc_config)
    if proc_config.autostart_enabled:
        manager.start()
        wait_ready_fn(
            config.get("webui_base_url"),
            timeout=proc_config.startup_timeout_seconds,
            poll_interval=0.5,
        )
    else:
        try:
            wait_ready_fn(
                config.get("webui_base_url"),
                timeout=min(float(proc_config.startup_timeout_seconds or 30.0), 2.0),
                poll_interval=0.5,
            )
        except Exception as exc:
            logger_module.info("WebUI not ready at startup; continuing unmanaged: %s", exc)
    return manager


def bootstrap_comfy(
    config: dict[str, Any],
    *,
    process_manager_cls: type[ComfyProcessManager] = ComfyProcessManager,
    wait_ready_fn: Callable[..., bool] = wait_for_comfy_ready,
    logger_module: Any = logging,
) -> ComfyProcessManager | None:
    proc_config = config.get("process_config")
    if proc_config is None and config.get("comfy_command"):
        proc_config = ComfyProcessConfig(
            command=list(config.get("comfy_command") or []),
            working_dir=config.get("comfy_workdir"),
            startup_timeout_seconds=float(config.get("comfy_startup_timeout_seconds") or 30.0),
            autostart_enabled=bool(config.get("comfy_autostart_enabled")),
            base_url=config.get("comfy_base_url"),
        )
    if proc_config is None:
        logger_module.info("No ComfyUI configuration available")
        base_url = config.get("comfy_base_url")
        if base_url:
            try:
                wait_ready_fn(base_url)
            except Exception as exc:
                logger_module.info("ComfyUI not available for unmanaged bootstrap probe: %s", exc)
        return None

    manager = process_manager_cls(proc_config)
    if proc_config.autostart_enabled:
        manager.start()
        wait_ready_fn(
            config.get("comfy_base_url"),
            timeout=proc_config.startup_timeout_seconds,
            poll_interval=0.5,
        )
    else:
        try:
            wait_ready_fn(
                config.get("comfy_base_url"),
                timeout=min(float(proc_config.startup_timeout_seconds or 30.0), 2.0),
                poll_interval=0.5,
            )
        except Exception as exc:
            logger_module.info("ComfyUI not ready at startup; continuing unmanaged: %s", exc)
    return manager


class ManagedRuntimeOwner:
    def __init__(self, *, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger(__name__)
        self._lock = threading.RLock()
        self._webui_manager: WebUIProcessManager | None = None
        self._comfy_manager: ComfyProcessManager | None = None
        self._webui_config: dict[str, Any] | None = None
        self._comfy_config: dict[str, Any] | None = None
        self._webui_state = "disconnected"
        self._comfy_state = "disconnected"
        self._webui_startup_error: str | None = None
        self._comfy_startup_error: str | None = None
        self._webui_bootstrap_started = False
        self._comfy_bootstrap_started = False

    def start_background_bootstrap(self) -> None:
        self._start_worker("webui")
        self._start_worker("comfy")

    def _start_worker(self, runtime_name: str) -> None:
        with self._lock:
            if runtime_name == "webui":
                if self._webui_bootstrap_started:
                    return
                self._webui_bootstrap_started = True
                target = self._bootstrap_webui_worker
                thread_name = "RuntimeHostWebUIBootstrap"
            else:
                if self._comfy_bootstrap_started:
                    return
                self._comfy_bootstrap_started = True
                target = self._bootstrap_comfy_worker
                thread_name = "RuntimeHostComfyBootstrap"
        thread = threading.Thread(target=target, name=thread_name, daemon=True)
        thread.start()

    def _bootstrap_webui_worker(self) -> None:
        config = load_webui_config()
        with self._lock:
            self._webui_config = dict(config)
            self._webui_state = "connecting"
            self._webui_startup_error = None
        proc_config = config.get("process_config")
        base_url = str(config.get("webui_base_url") or "")
        try:
            if proc_config is not None:
                manager = self._webui_manager or WebUIProcessManager(proc_config)
                with self._lock:
                    self._webui_manager = manager
                if bool(getattr(proc_config, "autostart_enabled", False)):
                    ready = bool(manager.ensure_running())
                    state = "ready" if ready else "error"
                else:
                    try:
                        ready = bool(manager.check_health())
                    except Exception as exc:
                        with self._lock:
                            self._webui_state = "disconnected"
                            self._webui_startup_error = str(exc)
                        self._logger.info(
                            "Runtime-host WebUI not ready during background bootstrap: %s",
                            exc,
                        )
                        return None
                    state = "ready" if ready else "disconnected"
            elif base_url:
                try:
                    ready = bool(
                        wait_for_webui_ready(
                            base_url,
                            timeout=BACKGROUND_STARTUP_PROBE_TIMEOUT_SECONDS,
                            poll_interval=BACKGROUND_STARTUP_PROBE_POLL_INTERVAL_SECONDS,
                            respect_failure_backoff=False,
                        )
                    )
                except Exception as exc:
                    with self._lock:
                        self._webui_state = "disconnected"
                        self._webui_startup_error = str(exc)
                    self._logger.info(
                        "Runtime-host WebUI not ready during background bootstrap: %s",
                        exc,
                    )
                    return None
                state = "ready" if ready else "disconnected"
            else:
                ready = False
                state = "disconnected"
            with self._lock:
                self._webui_state = state
                if ready:
                    self._webui_startup_error = None
        except Exception as exc:
            with self._lock:
                self._webui_state = "error"
                self._webui_startup_error = str(exc)
            self._logger.warning("Runtime-host WebUI bootstrap failed: %s", exc)

    def _bootstrap_comfy_worker(self) -> None:
        config = load_comfy_config()
        with self._lock:
            self._comfy_config = dict(config)
            self._comfy_state = "connecting"
            self._comfy_startup_error = None
        proc_config = config.get("process_config")
        base_url = str(config.get("comfy_base_url") or "")
        try:
            if proc_config is not None:
                manager = self._comfy_manager or ComfyProcessManager(proc_config)
                with self._lock:
                    self._comfy_manager = manager
                if bool(getattr(proc_config, "autostart_enabled", False)):
                    ready = bool(manager.ensure_running())
                    state = "ready" if ready else "error"
                else:
                    try:
                        ready = bool(manager.check_health())
                    except Exception as exc:
                        with self._lock:
                            self._comfy_state = "disconnected"
                            self._comfy_startup_error = str(exc)
                        self._logger.info(
                            "Runtime-host Comfy not ready during background bootstrap: %s",
                            exc,
                        )
                        return None
                    state = "ready" if ready else "disconnected"
            elif base_url:
                try:
                    ready = bool(
                        wait_for_comfy_ready(
                            base_url,
                            timeout=BACKGROUND_STARTUP_PROBE_TIMEOUT_SECONDS,
                            poll_interval=BACKGROUND_STARTUP_PROBE_POLL_INTERVAL_SECONDS,
                        )
                    )
                except Exception as exc:
                    with self._lock:
                        self._comfy_state = "disconnected"
                        self._comfy_startup_error = str(exc)
                    self._logger.info(
                        "Runtime-host Comfy not ready during background bootstrap: %s",
                        exc,
                    )
                    return None
                state = "ready" if ready else "disconnected"
            else:
                ready = False
                state = "disconnected"
            with self._lock:
                self._comfy_state = state
                if ready:
                    self._comfy_startup_error = None
        except Exception as exc:
            with self._lock:
                self._comfy_state = "error"
                self._comfy_startup_error = str(exc)
            self._logger.warning("Runtime-host Comfy bootstrap failed: %s", exc)

    def ensure_webui_ready(self, *, autostart: bool = True) -> dict[str, Any]:
        config = self._webui_config or load_webui_config()
        with self._lock:
            self._webui_config = dict(config)
            self._webui_state = "connecting"
            self._webui_startup_error = None
        proc_config = config.get("process_config")
        base_url = str(config.get("webui_base_url") or "")
        try:
            if proc_config is not None:
                manager = self._webui_manager or WebUIProcessManager(proc_config)
                with self._lock:
                    self._webui_manager = manager
                ready = bool(manager.ensure_running()) if autostart else bool(manager.check_health())
            else:
                ready = bool(
                    wait_for_webui_ready(
                        base_url,
                        timeout=BACKGROUND_STARTUP_PROBE_TIMEOUT_SECONDS,
                        poll_interval=BACKGROUND_STARTUP_PROBE_POLL_INTERVAL_SECONDS,
                        respect_failure_backoff=False,
                    )
                )
            with self._lock:
                self._webui_state = "ready" if ready else "error"
                if ready:
                    self._webui_startup_error = None
        except Exception as exc:
            with self._lock:
                self._webui_state = "error"
                self._webui_startup_error = str(exc)
        return dict(self.get_snapshot().get("webui") or {})

    def retry_webui_connection(self) -> dict[str, Any]:
        return self.ensure_webui_ready(autostart=True)

    def get_recent_webui_output_tail(self) -> dict[str, Any] | None:
        manager = self._webui_manager
        if manager is None:
            return None
        getter = getattr(manager, "get_recent_output_tail", None)
        if callable(getter):
            try:
                payload = getter()
                return dict(payload) if isinstance(payload, dict) else None
            except Exception:
                return None
        return None

    def get_snapshot(self) -> dict[str, Any]:
        with self._lock:
            webui_config = dict(self._webui_config or {})
            comfy_config = dict(self._comfy_config or {})
            webui_manager = self._webui_manager
            comfy_manager = self._comfy_manager
            webui_state = self._webui_state
            comfy_state = self._comfy_state
            webui_error = self._webui_startup_error
            comfy_error = self._comfy_startup_error
            webui_bootstrap_started = self._webui_bootstrap_started
            comfy_bootstrap_started = self._comfy_bootstrap_started
        webui_proc = webui_config.get("process_config")
        comfy_proc = comfy_config.get("process_config")
        return {
            "webui": {
                "managed": webui_proc is not None,
                "bootstrap_started": webui_bootstrap_started,
                "state": webui_state,
                "pid": getattr(webui_manager, "pid", None),
                "base_url": str(webui_config.get("webui_base_url") or ""),
                "autostart_enabled": bool(getattr(webui_proc, "autostart_enabled", False)),
                "startup_error": webui_error,
            },
            "comfy": {
                "managed": comfy_proc is not None,
                "bootstrap_started": comfy_bootstrap_started,
                "state": comfy_state,
                "pid": getattr(comfy_manager, "pid", None),
                "base_url": str(comfy_config.get("comfy_base_url") or ""),
                "autostart_enabled": bool(getattr(comfy_proc, "autostart_enabled", False)),
                "startup_error": comfy_error,
            },
        }

    def stop(self) -> None:
        webui_manager = self._webui_manager
        comfy_manager = self._comfy_manager
        if webui_manager is not None:
            stop = (
                getattr(webui_manager, "stop_webui", None)
                or getattr(webui_manager, "shutdown", None)
                or getattr(webui_manager, "stop", None)
            )
            if callable(stop):
                try:
                    stop()
                except Exception:
                    pass
        if comfy_manager is not None:
            stop = getattr(comfy_manager, "stop", None) or getattr(comfy_manager, "shutdown", None)
            if callable(stop):
                try:
                    stop()
                except Exception:
                    pass
        with self._lock:
            self._webui_state = "disconnected"
            self._comfy_state = "disconnected"


__all__ = [
    "ManagedRuntimeOwner",
    "bootstrap_comfy",
    "bootstrap_webui",
    "load_comfy_config",
    "load_webui_config",
]