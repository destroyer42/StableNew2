from __future__ import annotations

import time
from typing import Any

import requests


SYSTEM_STATS_PATH = "/system_stats"
OBJECT_INFO_PATH = "/object_info"


class ComfyHealthCheckTimeout(TimeoutError):
    """Raised when ComfyUI does not become ready in time."""


def _build_url(base_url: str, path: str) -> str:
    normalized = str(base_url or "").rstrip("/")
    if not normalized:
        return path
    return f"{normalized}{path}"


def _probe_json_endpoint(url: str, *, timeout: float) -> Exception | None:
    try:
        response = requests.get(url, timeout=timeout)
    except Exception as exc:
        return exc
    if response.status_code != 200:
        return RuntimeError(f"endpoint returned {response.status_code}")
    try:
        payload = response.json()
    except Exception as exc:
        return ValueError(f"invalid JSON: {exc}")
    if not isinstance(payload, dict):
        return RuntimeError(f"unexpected payload type {type(payload).__name__}")
    return None


def wait_for_comfy_ready(
    base_url: str,
    *,
    timeout: float = 30.0,
    poll_interval: float = 0.5,
) -> bool:
    deadline = time.time() + max(timeout, 0.0)
    poll_delay = max(poll_interval, 0.01)
    request_timeout = min(max(timeout, 0.01), 5.0)
    system_stats_url = _build_url(base_url, SYSTEM_STATS_PATH)
    object_info_url = _build_url(base_url, OBJECT_INFO_PATH)
    last_error: Exception | None = None

    while time.time() < deadline:
        system_error = _probe_json_endpoint(system_stats_url, timeout=request_timeout)
        if system_error is None:
            object_info_error = _probe_json_endpoint(object_info_url, timeout=request_timeout)
            if object_info_error is None:
                return True
            last_error = object_info_error
        else:
            last_error = system_error
        time.sleep(poll_delay)

    message = "ComfyUI did not become ready within allotted time"
    if last_error is not None:
        message = f"{message}: {last_error}"
    raise ComfyHealthCheckTimeout(message)


def validate_comfy_health(base_url: str, *, timeout: float = 5.0) -> dict[str, Any]:
    system_stats_url = _build_url(base_url, SYSTEM_STATS_PATH)
    object_info_url = _build_url(base_url, OBJECT_INFO_PATH)
    system_error = _probe_json_endpoint(system_stats_url, timeout=timeout)
    object_info_error = _probe_json_endpoint(object_info_url, timeout=timeout)
    return {
        "base_url": str(base_url or "").rstrip("/"),
        "healthy": system_error is None and object_info_error is None,
        "system_stats_ok": system_error is None,
        "object_info_ok": object_info_error is None,
        "errors": {
            "system_stats": None if system_error is None else str(system_error),
            "object_info": None if object_info_error is None else str(object_info_error),
        },
    }


__all__ = [
    "ComfyHealthCheckTimeout",
    "OBJECT_INFO_PATH",
    "SYSTEM_STATS_PATH",
    "validate_comfy_health",
    "wait_for_comfy_ready",
]
