"""Content-free event record (owner decision D7: no training-data capture).

A record may hold only the whitelisted fields below, and only short scalars: ids, codes, counts, a truncated digest and a
model hash prefix. Prompt text, suggestion text, file paths and asset names cannot be stored because no field can carry
them. There is no consent switch and no pair capture. The log is bounded and every write is atomic.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.utils.atomic_io import atomic_write_text

logger = logging.getLogger(__name__)

MAX_RECORDS = 1000
ALLOWED_FIELDS: frozenset[str] = frozenset(
    {
        "utc",
        "request_id",
        "kind",
        "outcome",
        "reason",
        "elapsed_ms",
        "input_chars",
        "output_chars",
        "request_digest",
        "model_sha256_prefix",
        "runtime_build_id",
        "strict_offline",
    }
)
_MAX_STRING = 80


class EventLog:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()

    @staticmethod
    def _check(record: dict[str, Any]) -> dict[str, Any]:
        unknown = set(record) - ALLOWED_FIELDS
        if unknown:
            raise ValueError(f"event field not allowed: {sorted(unknown)[0]}")
        for key, value in record.items():
            if value is None or isinstance(value, (bool, int, float)):
                continue
            if isinstance(value, str) and len(value) <= _MAX_STRING:
                continue
            raise ValueError(f"event field {key} must be a short scalar")
        return (
            {"utc": datetime.now(UTC).isoformat(), **record}
            if "utc" not in record
            else dict(record)
        )

    def append(self, record: dict[str, Any]) -> bool:
        """Append one record. Returns ``False`` (and logs) if the file could not be written; never raises on I/O."""

        checked = self._check(record)
        with self._lock:
            try:
                existing = self._read_lines()
                lines = [*existing[-(MAX_RECORDS - 1) :], json.dumps(checked, sort_keys=True)]
                atomic_write_text(self._path, "\n".join(lines) + "\n")
            except OSError:
                logger.warning("AI assist event record could not be written", exc_info=True)
                return False
        return True

    def tail(self, count: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            lines = self._read_lines()
        records: list[dict[str, Any]] = []
        for line in lines[-count:]:
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if isinstance(value, dict):
                records.append(value)
        return records

    def _read_lines(self) -> list[str]:
        try:
            text = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        return [line for line in text.splitlines() if line.strip()]


__all__ = ["ALLOWED_FIELDS", "MAX_RECORDS", "EventLog"]
