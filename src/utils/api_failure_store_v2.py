"""Central store for recent API failure records."""

from __future__ import annotations

import base64
import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


def _extract_image(payload: dict[str, Any] | None) -> str | None:
    if not payload:
        return None
    candidates = []
    for key in ("image", "images", "init_images"):
        value = payload.get(key)
        if isinstance(value, list) and value:
            candidates.extend(value)
        elif isinstance(value, str):
            candidates.append(value)
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            normalized = candidate.strip()
            if normalized.startswith("data:"):
                try:
                    _, payload_part = normalized.split(",", 1)
                except ValueError:
                    payload_part = normalized.split(",", 1)[-1]
            else:
                payload_part = normalized
            try:
                base64.b64decode(payload_part, validate=True)
                return payload_part
            except Exception:
                continue
    return None


#: Always-on script unit fields that carry (base64) image bytes. The pinned Forge ControlNet unit accepts the pose as
#: ``image`` (a string, or the older ``{"image": ..., "mask": ...}`` dict) and the optional masks/foregrounds below.
_SCRIPT_IMAGE_KEYS = ("image", "mask_image", "image_fg", "mask_image_fg")
_SCRIPT_IMAGE_MEMBERS = ("image", "mask")


def _omitted(value: str) -> str:
    return f"<{len(value)} base64 characters omitted>"


def _redact_script_image_value(value: Any) -> Any:
    """The value with any non-empty image string replaced by a size marker (length is irrelevant: a small PNG is data)."""

    if isinstance(value, str):
        return _omitted(value) if value else value
    if isinstance(value, dict):
        return {
            key: _omitted(member) if key in _SCRIPT_IMAGE_MEMBERS and isinstance(member, str) and member else member
            for key, member in value.items()
        }
    return value


def _redact_script_images(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """A copy of ``payload`` whose always-on script units carry no image bytes (PR-IMG-CNET-210).

    A ControlNet unit nests its (base64) images under ``alwayson_scripts.<script>.args[*]`` (``image``, ``mask_image``,
    ``image_fg``, ``mask_image_fg``). Failure records are shown in a text widget and kept in memory, so every non-empty
    image string there is replaced by a size marker whatever its encoded length; every other field, and the top-level
    ``image``/``init_images`` handling, is untouched. The caller's payload is never mutated.
    """

    if not isinstance(payload, dict) or not isinstance(payload.get("alwayson_scripts"), dict):
        return payload
    scripts: dict[str, Any] = {}
    for name, script in payload["alwayson_scripts"].items():
        args = script.get("args") if isinstance(script, dict) else None
        if not isinstance(args, list):
            scripts[name] = script
            continue
        cleaned = []
        for arg in args:
            if isinstance(arg, dict):
                arg = {
                    key: _redact_script_image_value(value) if key in _SCRIPT_IMAGE_KEYS else value
                    for key, value in arg.items()
                }
            cleaned.append(arg)
        scripts[name] = {**script, "args": cleaned}
    return {**payload, "alwayson_scripts": scripts}


@dataclass
class ApiFailureRecord:
    timestamp: float
    stage: str | None
    endpoint: str
    method: str
    status_code: int | None
    error_message: str
    response_text: str | None
    payload: dict[str, Any] | None = None
    image_base64: str | None = None


class ApiFailureStore:
    """Ring buffer for API failure records."""

    def __init__(self, max_entries: int = 20):
        self._max_entries = max_entries
        self._records: deque[ApiFailureRecord] = deque(maxlen=max_entries)

    def record(
        self,
        *,
        stage: str | None,
        endpoint: str,
        method: str,
        payload: dict[str, Any] | None,
        status_code: int | None,
        response_text: str | None,
        error_message: str,
    ) -> None:
        image_b64 = _extract_image(payload)
        payload = _redact_script_images(payload)
        record = ApiFailureRecord(
            timestamp=time.time(),
            stage=stage,
            endpoint=endpoint,
            method=method,
            status_code=status_code,
            response_text=response_text,
            payload=payload,
            error_message=error_message,
            image_base64=image_b64,
        )
        self._records.append(record)
        logger.debug("Recorded API failure %s %s", method, endpoint)

    def get_recent(self, limit: int | None = None) -> list[ApiFailureRecord]:
        records = list(self._records)
        if limit is not None:
            records = records[-limit:]
        return list(reversed(records))

    def clear(self) -> None:
        self._records.clear()


_GLOBAL_STORE = ApiFailureStore()


def record_api_failure(
    *,
    stage: str | None,
    endpoint: str,
    method: str,
    payload: dict[str, Any] | None,
    status_code: int | None,
    response_text: str | None,
    error_message: str,
) -> None:
    try:
        _GLOBAL_STORE.record(
            stage=stage,
            endpoint=endpoint,
            method=method,
            payload=payload,
            status_code=status_code,
            response_text=response_text,
            error_message=error_message,
        )
    except Exception:
        logger.debug("Failed to record API failure", exc_info=True)


def get_api_failures(limit: int = 5) -> list[ApiFailureRecord]:
    return _GLOBAL_STORE.get_recent(limit=limit)


def clear_api_failures() -> None:
    _GLOBAL_STORE.clear()
