"""Deterministic grouping identity for JSON-like Learning variant values.

Scalar variant values (numbers, strings, booleans) group by themselves, exactly
as before.  Structured values such as a LoRA Strength variant
``{"name": "add-detail-xl", "weight": 1.0}`` are unhashable, so grouping uses a
canonical key while the original value stays the semantic value that callers
see.  The key is independent of mapping insertion order, keeps every field
(a LoRA's name is part of its identity), and never collides across different
structures.
"""

from __future__ import annotations

import json
import math
from collections.abc import Hashable, Mapping, Sequence
from typing import Any

_MAX_DEPTH = 32
_COMPOSITE_TAG = "composite"


class VariantValueError(ValueError):
    """A variant value cannot be given a deterministic grouping identity."""


def _normalize(value: Any, depth: int) -> Any:
    if depth > _MAX_DEPTH:
        raise VariantValueError("variant value is nested too deeply")
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise VariantValueError(f"non-finite number {value!r} has no stable identity")
        # 1 and 1.0 are the same weight; keep other floats exact.
        return int(value) if value.is_integer() else value
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            name = str(key)
            if name in normalized:
                raise VariantValueError(f"mapping keys collide after string conversion: {name!r}")
            normalized[name] = _normalize(item, depth + 1)
        return normalized
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [_normalize(item, depth + 1) for item in value]
    raise VariantValueError(f"unsupported variant value type {type(value).__name__}")


def canonical_value_key(value: Any) -> Hashable:
    """Return a hashable, order-independent grouping key for ``value``.

    Raises :class:`VariantValueError` (never ``TypeError``) for values that are
    not JSON-like, so callers can skip one record instead of failing a whole
    recommendation pass.
    """

    if value is None or isinstance(value, (bool, int, float, str)):
        return value  # scalars keep their existing grouping behavior
    normalized = _normalize(value, 0)
    return (
        _COMPOSITE_TAG,
        json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=True),
    )


def plain_value(value: Any) -> Any:
    """A detached plain JSON-like copy of ``value`` (dicts/lists) for public results."""

    if isinstance(value, Mapping):
        return {key: plain_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [plain_value(item) for item in value]
    return value
