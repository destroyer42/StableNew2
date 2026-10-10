"""Shared value types for the PR-IMG-MODELS-154A safety-preparation contracts (pure; no I/O, no clock reads)."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

GIB = 1024**3
MIB = 1024**2

# Observation status. Anything other than OK is never evidence of a pass, and never silently becomes zero.
OK, MISSING, STALE, ERROR, INVALID = "ok", "missing", "stale", "error", "invalid"

# Tolerated observation-timestamp skew ahead of the evaluating clock before a sample is called invalid.
CLOCK_SKEW_TOLERANCE_S = 0.5


def valid_time(value: object) -> bool:
    """Finite nonnegative seconds in the injected monotonic domain; booleans are not times."""
    return (
        not isinstance(value, bool)
        and isinstance(value, int | float)
        and math.isfinite(value)
        and value >= 0
    )


def valid_utc(value: object) -> bool:
    """An explicitly supplied wall-clock timestamp must be an aware ISO timestamp."""
    if not isinstance(value, str):
        return False
    try:
        taken = datetime.fromisoformat(value)
        return taken.tzinfo is not None and math.isfinite(taken.timestamp())
    except (ValueError, TypeError, OverflowError, OSError):
        return False


@dataclass(frozen=True)
class Finding:
    """One coded reason. ``severity``: ``refuse`` (hard refusal), ``inconclusive`` (cannot be assessed), ``info``."""

    code: str
    severity: str
    detail: str = ""


@dataclass(frozen=True)
class Observation:
    """A measured value with its provenance. ``observed_mono_s`` is a monotonic timestamp from the evaluating clock domain."""

    name: str
    value: float | int | str | bool | None
    units: str
    source: str
    observed_mono_s: float | None = None
    observed_utc: str | None = None
    status: str = OK
    detail: str = ""

    def number(
        self,
        *,
        units: str,
        now_mono_s: float,
        max_age_s: float,
        allow_negative: bool = False,
    ) -> tuple[float | None, str | None]:
        """``(value, None)`` when the observation is usable evidence, otherwise ``(None, reason_code)``.

        Missing, errored, stale, wrongly-united, non-finite, boolean, non-numeric, negative or future-dated readings are
        all refused so a failed sensor can never be mistaken for a zero or a pass.
        """

        if self.observed_utc is not None and not valid_utc(self.observed_utc):
            return None, INVALID
        if self.status != OK:
            return None, self.status
        if self.units != units:
            return None, "units_invalid"
        value = self.value
        if value is None:
            return None, MISSING
        if isinstance(value, bool) or not isinstance(value, int | float):
            return None, INVALID
        number = float(value)
        if not math.isfinite(number):
            return None, INVALID
        if number < 0 and not allow_negative:
            return None, INVALID
        if self.observed_mono_s is None:
            return None, STALE
        if not all(valid_time(v) for v in (self.observed_mono_s, now_mono_s, max_age_s)):
            return None, INVALID
        age = now_mono_s - self.observed_mono_s
        if not math.isfinite(age):
            return None, INVALID
        if age < -CLOCK_SKEW_TOLERANCE_S:
            return None, "clock_skew"
        if age > max_age_s:
            return None, STALE
        return number, None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "units": self.units,
            "source": self.source,
            "observed_mono_s": self.observed_mono_s,
            "observed_utc": self.observed_utc,
            "status": self.status,
            "detail": self.detail,
        }


def canonical_json(value: Any) -> str:
    """Deterministic JSON; NaN/Infinity are rejected rather than serialized."""

    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("ascii")).hexdigest()


def is_hex_digest(value: object, *, length: int = 64) -> bool:
    return (
        isinstance(value, str)
        and len(value) == length
        and all(c in "0123456789abcdef" for c in value)
    )


def findings_codes(findings: tuple[Finding, ...] | list[Finding]) -> list[str]:
    return [item.code for item in findings]


def require_mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a mapping")
    return value
