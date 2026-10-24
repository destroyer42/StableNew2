from __future__ import annotations

import re

_SPACE_PATTERN = re.compile(r"\s+")


def normalize_for_match(text: str) -> str:
    value = _SPACE_PATTERN.sub(" ", str(text or "").strip().lower())
    value = value.replace("( ", "(").replace(" )", ")")
    value = value.replace("[ ", "[").replace(" ]", "]")
    value = value.replace("< ", "<").replace(" >", ">")
    return value


def build_dedupe_key(text: str) -> str:
    """
    Strip cosmetic syntax while preserving attention and extra-network identity.
    """
    normalized = normalize_for_match(text)
    if not normalized:
        return ""
    # Bare parentheses/brackets also change attention in WebUI. They are not
    # cosmetic wrappers, even without an explicit numeric weight.
    if any(char in normalized for char in "()[]<>"):
        return normalized
    normalized = normalized.replace("_", " ")
    normalized = normalized.replace("-", " ")
    normalized = re.sub(r"[\"'`]", "", normalized)
    normalized = _SPACE_PATTERN.sub(" ", normalized).strip()
    return normalized
