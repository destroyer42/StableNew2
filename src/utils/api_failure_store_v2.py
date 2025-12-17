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
