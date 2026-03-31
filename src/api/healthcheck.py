from __future__ import annotations

import logging
import time
from typing import Any

import requests

from src.utils import LogContext, get_logger, log_with_ctx

PROGRESS_PATH = "/sdapi/v1/progress"
MODELS_PATH = "/sdapi/v1/sd-models"
OPTIONS_PATH = "/sdapi/v1/options"
_SHORT_PORT_PROBE_TIMEOUT = 3.0
_SHORT_PORT_PROBE_INTERVAL = 1.0
_READINESS_FAILURE_STATE: dict[str, dict[str, float]] = {}
_HARD_FAILURE_THRESHOLD = 2
_READINESS_BACKOFF_BASE_SEC = 15.0
_READINESS_BACKOFF_MAX_SEC = 90.0


class WebUIHealthCheckTimeout(TimeoutError):
    """Raised when WebUI does not respond within the allotted time."""


def _is_hard_connection_failure(exc: Exception | None) -> bool:
    if exc is None:
        return False
    if isinstance(exc, requests.exceptions.ConnectionError):
        return True
    text = str(exc).lower()
    return "actively refused" in text or "failed to establish a new connection" in text


def _readiness_cooldown_remaining(base_url: str) -> float:
    state = _READINESS_FAILURE_STATE.get(base_url) or {}
    until = float(state.get("cooldown_until", 0.0) or 0.0)
    remaining = until - time.monotonic()
    if remaining <= 0:
        if base_url in _READINESS_FAILURE_STATE:
            _READINESS_FAILURE_STATE[base_url]["cooldown_until"] = 0.0
        return 0.0
    return remaining


def _record_readiness_failure(base_url: str, exc: Exception | None) -> None:
    if not _is_hard_connection_failure(exc):
        return
    state = _READINESS_FAILURE_STATE.setdefault(base_url, {"hard_failures": 0.0, "cooldown_until": 0.0})
    state["hard_failures"] = float(state.get("hard_failures", 0.0) or 0.0) + 1.0
    hard_failures = int(state["hard_failures"])
    if hard_failures < _HARD_FAILURE_THRESHOLD:
        return
    exponent = max(0, hard_failures - _HARD_FAILURE_THRESHOLD)
    cooldown = min(_READINESS_BACKOFF_BASE_SEC * (2**exponent), _READINESS_BACKOFF_MAX_SEC)
    state["cooldown_until"] = time.monotonic() + cooldown


def _clear_readiness_failure(base_url: str) -> None:
    _READINESS_FAILURE_STATE.pop(base_url, None)


def clear_readiness_failure_state(base_url: str | None = None) -> None:
    """Clear cached readiness backoff state for one base URL or all URLs."""

    if base_url:
        _clear_readiness_failure(base_url)
        return
    _READINESS_FAILURE_STATE.clear()


def get_readiness_failure_state(base_url: str) -> dict[str, float]:
    """Return a snapshot of readiness failure state for diagnostics."""

    state = _READINESS_FAILURE_STATE.get(base_url) or {}
    return {
        "hard_failures": float(state.get("hard_failures", 0.0) or 0.0),
        "cooldown_remaining_s": _readiness_cooldown_remaining(base_url),
    }


def _build_url(base_url: str, path: str) -> str:
    normalized = (base_url or "").rstrip("/")
    if not normalized:
        return path
    return f"{normalized}{path}"


def _probe_json_endpoint(url: str, endpoint: str, timeout: float) -> Exception | None:
    try:
        response = requests.get(url, timeout=timeout)
    except Exception as exc:
        return exc
    if response.status_code != 200:
        return RuntimeError(f"{endpoint} returned {response.status_code}")
    try:
        payload = response.json()
    except Exception as exc:
        return ValueError(f"{endpoint} invalid JSON: {exc}")
    if not isinstance(payload, (list, dict)):
        return RuntimeError(f"{endpoint} returned unexpected payload type {type(payload).__name__}")
    return None


def _probe_progress_endpoint(url: str, timeout: float) -> bool:
    try:
        response = requests.get(url, timeout=timeout)
    except Exception:
        return False
    return response.status_code == 200


def wait_for_webui_ready(
    base_url: str,
    timeout: float = 30.0,
    poll_interval: float = 0.5,
    *,
    respect_failure_backoff: bool = True,
) -> bool:
    logger = get_logger(__name__)
    ctx = LogContext(subsystem="api")
    cooldown_remaining = _readiness_cooldown_remaining(base_url) if respect_failure_backoff else 0.0
    if cooldown_remaining > 0:
        msg = f"WebUI readiness backoff active for {cooldown_remaining:.1f}s"
        log_with_ctx(
            logger,
            logging.DEBUG,
            msg,
            ctx=ctx,
            extra_fields={"event": "webui_readiness_backoff", "base_url": base_url, "cooldown_remaining_s": cooldown_remaining},
        )
        raise WebUIHealthCheckTimeout(msg)
    log_with_ctx(
        logger,
        logging.DEBUG,
        "healthcheck.wait_for_webui_ready",
        ctx=ctx,
        extra_fields={
            "base_url": base_url,
            "timeout": timeout,
            "poll_interval": poll_interval,
            "respect_failure_backoff": respect_failure_backoff,
        },
    )

    deadline = time.time() + max(timeout, 0)
    poll_delay = max(poll_interval, 0.01)
    request_timeout = min(max(timeout, 0.01), 5.0)
    models_url = _build_url(base_url, MODELS_PATH)
    options_url = _build_url(base_url, OPTIONS_PATH)
    progress_url = _build_url(base_url, PROGRESS_PATH)

    log_with_ctx(
        logger,
        logging.DEBUG,
        "Probing WebUI readiness at models/options endpoints",
        ctx=ctx,
        extra_fields={"models_endpoint": MODELS_PATH, "options_endpoint": OPTIONS_PATH},
    )

    last_error: Exception | None = None
    last_error_endpoint: str | None = None

    while time.time() < deadline:
        models_error = _probe_json_endpoint(models_url, MODELS_PATH, request_timeout)
        if models_error is None:
            _clear_readiness_failure(base_url)
            log_with_ctx(
                logger,
                logging.DEBUG,
                f"WebUI API ready (models endpoint): {models_url}",
                ctx=ctx,
                extra_fields={"endpoint": MODELS_PATH},
            )
            return True

        last_error = models_error
        last_error_endpoint = MODELS_PATH
        log_with_ctx(
            logger,
            logging.DEBUG,
            "WebUI models endpoint probe failed",
            ctx=ctx,
            extra_fields={"endpoint": MODELS_PATH, "error": str(models_error)},
        )

        options_error = _probe_json_endpoint(options_url, OPTIONS_PATH, request_timeout)
        if options_error is None:
            _clear_readiness_failure(base_url)
            log_with_ctx(
                logger,
                logging.DEBUG,
                f"WebUI API ready (options endpoint): {options_url}",
                ctx=ctx,
                extra_fields={"endpoint": OPTIONS_PATH},
            )
            return True

        last_error = options_error
        last_error_endpoint = OPTIONS_PATH
        log_with_ctx(
            logger,
            logging.DEBUG,
            "WebUI options endpoint probe failed",
            ctx=ctx,
            extra_fields={"endpoint": OPTIONS_PATH, "error": str(options_error)},
        )

        if _probe_progress_endpoint(progress_url, request_timeout):
            extra_fields: dict[str, Any] = {"endpoint": PROGRESS_PATH}
            if last_error is not None:
                extra_fields["last_error"] = str(last_error)
            if last_error_endpoint:
                extra_fields["last_error_endpoint"] = last_error_endpoint
            log_with_ctx(
                logger,
                logging.INFO,
                f"WebUI API reachable but models/options not ready yet: {progress_url}",
                ctx=ctx,
                extra_fields=extra_fields,
            )

        time.sleep(poll_delay)

    msg = "WebUI did not become ready within allotted time"
    if last_error:
        if respect_failure_backoff:
            _record_readiness_failure(base_url, last_error)
        msg = f"{msg}: {last_error}"
        log_with_ctx(
            logger,
            logging.WARNING,
            msg,
            ctx=ctx,
            extra_fields={
                "last_error": str(last_error),
                "last_error_endpoint": last_error_endpoint,
                "event": "webui_readiness_timeout",
                "hard_connection_failure": _is_hard_connection_failure(last_error),
            },
        )
    else:
        log_with_ctx(logger, logging.WARNING, msg, ctx=ctx)
    raise WebUIHealthCheckTimeout(msg)


def find_webui_port(
    base_url_template: str = "http://127.0.0.1:{port}", ports: list[int] | None = None
) -> str | None:
    """Try to find WebUI running on common ports."""
    if ports is None:
        ports = [7860, 7861, 7862, 7863, 7864, 8000, 8080, 5000]

    logger = get_logger(__name__)
    ctx = LogContext(subsystem="api")

    for port in ports:
        url = base_url_template.format(port=port)
        log_with_ctx(
            logger,
            logging.DEBUG,
            f"Checking for WebUI API on port {port}",
            ctx=ctx,
            extra_fields={"port": port, "endpoint": PROGRESS_PATH},
        )
        try:
            if wait_for_webui_ready(
                url, timeout=_SHORT_PORT_PROBE_TIMEOUT, poll_interval=_SHORT_PORT_PROBE_INTERVAL
            ):
                log_with_ctx(
                    logger,
                    logging.DEBUG,
                    f"Found WebUI API on port {port}",
                    ctx=ctx,
                    extra_fields={"port": port},
                )
                return url
        except WebUIHealthCheckTimeout:
            log_with_ctx(
                logger,
                logging.DEBUG,
                f"WebUI API on port {port} is not ready yet",
                ctx=ctx,
                extra_fields={"port": port},
            )
        except Exception as exc:
            log_with_ctx(
                logger,
                logging.DEBUG,
                f"Port {port} API not responding: {exc}",
                ctx=ctx,
                extra_fields={"port": port},
            )

            try:
                web_url = f"{url.rstrip('/')}/"
                log_with_ctx(
                    logger,
                    logging.DEBUG,
                    f"Checking for WebUI web interface on port {port}: {web_url}",
                    ctx=ctx,
                    extra_fields={"port": port},
                )
                response = requests.get(web_url, timeout=2.0)
                if response.status_code == 200:
                    log_with_ctx(
                        logger,
                        logging.WARNING,
                        f"Found WebUI web interface on port {port} but API not enabled. Please start WebUI with --api flag.",
                        ctx=ctx,
                        extra_fields={"port": port},
                    )
            except Exception:
                pass

    return None
