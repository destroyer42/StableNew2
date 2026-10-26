from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

EMBEDDING_WEIGHTED_RE = re.compile(
    r"\(\s*<embedding:([^>]+)>\s*:\s*([+-]?\d+(?:\.\d+)?)\s*\)",
    re.IGNORECASE,
)
EMBEDDING_PLAIN_RE = re.compile(r"<embedding:([^>]+)>", re.IGNORECASE)
LEGACY_EMBEDDING_RE = re.compile(
    r"<(?!\s*(?:embedding|lora):)([A-Za-z0-9_.-]+)>",
    re.IGNORECASE,
)


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


# Characters that A1111/Forge prompt parsing treats as syntax. An embedding whose name contains one cannot be
# invoked by its bare filename token (it would be split, grouped or parsed as an extra network).
_UNSAFE_INVOCATION_CHARS = frozenset("<>()[]{}:,|" + chr(92) + chr(10) + chr(13) + chr(9))


def is_invocable_embedding_name(name: str) -> bool:
    """True when ``name`` can be written into a prompt as a bare textual-inversion token."""
    cleaned = str(name or "")
    if not cleaned.strip() or cleaned != cleaned.strip():
        return False
    return not any(char in _UNSAFE_INVOCATION_CHARS for char in cleaned)


def render_embedding_invocation(name: str, weight: float = 1.0) -> str:
    """Render the prompt text the pinned A1111/Forge text encoder understands.

    A textual inversion is invoked by its filename stem, not by an ``<embedding:...>`` extra-network tag:
    Forge's ``parse_prompts`` removes unregistered ``<name:args>`` tags before tokenization, so that notation
    never reaches the encoder. Weight is ordinary prompt attention, ``(Name:w)``; it is not an embedding
    multiplier and weight 0 does not remove the embedding (callers omit an absent embedding entirely).
    ``render_embedding_reference`` stays the PromptPack authoring/storage notation.
    """
    cleaned_name = str(name or "").strip()
    if not cleaned_name:
        return ""
    if abs(float(weight) - 1.0) < 1e-6:
        return cleaned_name
    return f"({cleaned_name}:{format_embedding_weight(weight)})"


def textual_inversion_report(info: Any) -> dict[str, Any] | None:
    """The textual-inversion report Forge Neo puts in ``extra_generation_params['TI']`` of a generation response.

    ``None`` when the response carried no ``extra_generation_params`` at all (nothing was reported); otherwise
    ``{"reported": True, "names": [...]}`` (an empty list when no embedding was reported as used). The backend
    reports embedding *names* only: no hash, polarity or applied weight.
    """
    params = info.get("extra_generation_params") if isinstance(info, dict) else None
    if not isinstance(params, dict):
        return None
    raw = params.get("TI")
    names = [part.strip() for part in str(raw).split(",") if part.strip()] if raw else []
    return {"reported": True, "names": names}


def extract_embedding_entries(text: str) -> list[tuple[str, float]]:
    entries: list[tuple[str, float]] = []
    working = str(text or "")
    for match in EMBEDDING_WEIGHTED_RE.finditer(working):
        entries.append((match.group(1).strip(), _coerce_weight(match.group(2), 1.0)))
    working = EMBEDDING_WEIGHTED_RE.sub(" ", working)
    for match in EMBEDDING_PLAIN_RE.finditer(working):
        entries.append((match.group(1).strip(), 1.0))
    working = EMBEDDING_PLAIN_RE.sub(" ", working)
    for match in LEGACY_EMBEDDING_RE.finditer(working):
        entries.append((match.group(1).strip(), 1.0))
    return [(name, weight) for name, weight in entries if name]


def extract_embedding_token_strings(text: str) -> list[str]:
    tokens: list[str] = []
    working = str(text or "")
    for match in EMBEDDING_WEIGHTED_RE.finditer(working):
        token = match.group(0).strip()
        if token:
            tokens.append(token)
    working = EMBEDDING_WEIGHTED_RE.sub(" ", working)
    for match in EMBEDDING_PLAIN_RE.finditer(working):
        token = match.group(0).strip()
        if token:
            tokens.append(token)
    working = EMBEDDING_PLAIN_RE.sub(" ", working)
    for match in LEGACY_EMBEDDING_RE.finditer(working):
        token = match.group(0).strip()
        if token:
            tokens.append(token)
    return tokens


def strip_embedding_entries(text: str) -> str:
    stripped = EMBEDDING_WEIGHTED_RE.sub(" ", str(text or ""))
    stripped = EMBEDDING_PLAIN_RE.sub(" ", stripped)
    stripped = LEGACY_EMBEDDING_RE.sub(" ", stripped)
    return " ".join(stripped.split()).strip()
