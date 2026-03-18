from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

EMBEDDING_WEIGHTED_RE = re.compile(
    r"\(\s*<embedding:([^>]+)>\s*:\s*([+-]?\d+(?:\.\d+)?)\s*\)",
    re.IGNORECASE,
)
EMBEDDING_PLAIN_RE = re.compile(r"<embedding:([^>]+)>", re.IGNORECASE)


def _coerce_weight(value: Any, default: float = 1.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_embedding_entries(values: Iterable[Any] | None) -> list[tuple[str, float]]:
    normalized: list[tuple[str, float]] = []
    for value in values or []:
        if isinstance(value, str):
            name = value.strip()
            if name:
                normalized.append((name, 1.0))
            continue
        if isinstance(value, dict):
            name = str(value.get("name", "") or "").strip()
            if name:
                normalized.append((name, _coerce_weight(value.get("weight"), 1.0)))
            continue
        if isinstance(value, (list, tuple)) and value:
            name = str(value[0] or "").strip()
            if name:
                weight = _coerce_weight(value[1] if len(value) > 1 else 1.0, 1.0)
                normalized.append((name, weight))
    return normalized


def serialize_embedding_entries(values: Iterable[Any] | None) -> list[Any]:
    serialized: list[Any] = []
    for name, weight in normalize_embedding_entries(values):
        if abs(weight - 1.0) < 1e-6:
            serialized.append(name)
        else:
            serialized.append([name, weight])
    return serialized


def format_embedding_weight(weight: float) -> str:
    return f"{float(weight):g}"


def render_embedding_reference(name: str, weight: float = 1.0) -> str:
    cleaned_name = str(name or "").strip()
    if not cleaned_name:
        return ""
    if abs(float(weight) - 1.0) < 1e-6:
        return f"<embedding:{cleaned_name}>"
    return f"(<embedding:{cleaned_name}>:{format_embedding_weight(weight)})"


def extract_embedding_entries(text: str) -> list[tuple[str, float]]:
    entries: list[tuple[str, float]] = []
    working = str(text or "")
    for match in EMBEDDING_WEIGHTED_RE.finditer(working):
        entries.append((match.group(1).strip(), _coerce_weight(match.group(2), 1.0)))
    working = EMBEDDING_WEIGHTED_RE.sub(" ", working)
    for match in EMBEDDING_PLAIN_RE.finditer(working):
        entries.append((match.group(1).strip(), 1.0))
    return [(name, weight) for name, weight in entries if name]


def strip_embedding_entries(text: str) -> str:
    stripped = EMBEDDING_WEIGHTED_RE.sub(" ", str(text or ""))
    stripped = EMBEDDING_PLAIN_RE.sub(" ", stripped)
    return " ".join(stripped.split()).strip()
