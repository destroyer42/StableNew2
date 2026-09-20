"""Deterministic LoRA-strength variants for controlled Learning experiments.

The executable A1111 prompt is the only LoRA execution authority.  A Learning
variant therefore rewrites the frozen positive prompt before NJR construction,
and executed evidence is validated against the prompt readback.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping
from typing import Any

_LORA_TOKEN_RE = re.compile(r"<lora:([^:>]+):([^>]+)>", re.IGNORECASE)


def format_lora_token(name: str, weight: float) -> str:
    return f"<lora:{name}:{float(weight)}>"


def extract_lora_tokens(prompt: str) -> list[tuple[str, str]]:
    """Return (name, raw weight text) for every LoRA token in a prompt."""

    return [
        (m.group(1).strip(), m.group(2).strip()) for m in _LORA_TOKEN_RE.finditer(prompt or "")
    ]


def _same(a: str, b: str) -> bool:
    return a.strip().casefold() == b.strip().casefold()


def apply_lora_variant(prompt: str, name: str, weight: float) -> str:
    """Set exactly one token for ``name`` at ``weight`` (none when weight is 0)."""

    name = str(name or "").strip()
    weight = float(weight)
    if not name:
        raise ValueError("LoRA variant requires a LoRA name")
    if weight < 0:
        raise ValueError(f"LoRA weight must be >= 0, got {weight}")
    replacement = format_lora_token(name, weight) if weight > 0 else ""
    placed = False

    def _swap(match: re.Match[str]) -> str:
        nonlocal placed
        if not _same(match.group(1), name):
            return match.group(0)
        if placed or not replacement:
            return ""
        placed = True
        return replacement

    result = _LORA_TOKEN_RE.sub(_swap, prompt or "")
    result = re.sub(r"[ \t]{2,}", " ", result)
    result = re.sub(r"\s+,", ",", result)
    result = re.sub(r"(,\s*){2,}", ", ", result).strip().strip(",").strip()
    if replacement and not placed:
        result = f"{result} {replacement}".strip()
    return result


def _weight_matches(raw: str, expected: float) -> bool:
    try:
        return abs(float(raw) - float(expected)) < 1e-9
    except ValueError:
        return False


def validate_lora_variant(
    prompt: str,
    name: str,
    weight: float,
    *,
    baseline_prompt: str | None = None,
) -> str:
    """Return "" when ``prompt`` executes the variant exactly, else a reason code."""

    if not (prompt or "").strip():
        return "lora_readback_unavailable"
    selected = [w for n, w in extract_lora_tokens(prompt) if _same(n, name)]
    if float(weight) <= 0:
        if selected:
            return "lora_strength_mismatch"
    elif len(selected) != 1 or not _weight_matches(selected[0], weight):
        return "lora_strength_mismatch"
    if baseline_prompt is not None:
        def others(text: str) -> Counter[tuple[str, str]]:
            return Counter(
                (n.casefold(), w) for n, w in extract_lora_tokens(text) if not _same(n, name)
            )

        if others(prompt) != others(baseline_prompt):
            return "lora_unrelated_changed"
    return ""


def lora_variant_from_value(value: Any) -> tuple[str, float] | None:
    """Parse a composite {"name","weight"} variant value."""

    if isinstance(value, Mapping) and value.get("name") not in (None, "") and "weight" in value:
        return str(value["name"]), float(value["weight"])
    return None


def lora_value_label(value: Any) -> str:
    """Readable bounded label for a composite LoRA value, e.g. add-detail-xl-0p25."""

    parsed = lora_variant_from_value(value)
    if parsed is None:
        return ""
    name = re.sub(r"[^A-Za-z0-9\-]+", "-", parsed[0]).strip("-")[:24] or "lora"
    return f"{name}-{parsed[1]!r}".replace(".", "p")


def validate_executed_lora(executed_config: Any, final_prompt: Any) -> str:
    """Validate readback against a variant's lora_override; "" when not applicable/valid."""

    override = executed_config.get("lora_override") if isinstance(executed_config, Mapping) else None
    parsed = lora_variant_from_value(override)
    if parsed is None:
        return ""
    return validate_lora_variant(str(final_prompt or ""), parsed[0], parsed[1])
