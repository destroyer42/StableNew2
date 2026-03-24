from __future__ import annotations

import re

from src.prompting.prompt_splitter import detect_lora_syntax, detect_weight_syntax

_SPACE_PATTERN = re.compile(r"\s+")
_OUTER_WRAPPER_PATTERN = re.compile(r"^[\[(](.+?)[\])]$")
_PAREN_WEIGHT_PATTERN = re.compile(r"^\((.+?):[+-]?\d+(?:\.\d+)?\)$")
def normalize_for_match(text: str) -> str:
    value = _SPACE_PATTERN.sub(" ", str(text or "").strip().lower())
    value = value.replace("( ", "(").replace(" )", ")")
    value = value.replace("[ ", "[").replace(" ]", "]")
    value = value.replace("< ", "<").replace(" >", ">")
    return value


def build_dedupe_key(text: str) -> str:
    """
    Strip cosmetic syntax for duplicate matching while preserving concept identity.
    """
    normalized = normalize_for_match(text)
    if not normalized:
        return ""
    if detect_lora_syntax(normalized):
        return normalized
    if detect_weight_syntax(normalized):
        return normalized
    weight_match = _PAREN_WEIGHT_PATTERN.match(normalized)
    if weight_match:
        normalized = weight_match.group(1).strip()
    outer_match = _OUTER_WRAPPER_PATTERN.match(normalized)
    if outer_match:
        normalized = outer_match.group(1).strip()
    normalized = normalized.replace("_", " ")
    normalized = normalized.replace("-", " ")
    normalized = re.sub(r"[\"'`]", "", normalized)
    normalized = _SPACE_PATTERN.sub(" ", normalized).strip()
    return normalized
