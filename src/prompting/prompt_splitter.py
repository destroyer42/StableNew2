from __future__ import annotations

import re
from typing import List


_LORA_PATTERN = re.compile(r"<\s*lora\s*:[^>]+>", re.IGNORECASE)
_WEIGHT_PATTERN = re.compile(r"^\s*[\[(].+:[+-]?\d+(?:\.\d+)?[\])]\s*$")


def split_prompt_chunks(prompt: str) -> List[str]:
    """
    Split prompt on commas that are not inside (), [], or <>.
    Preserve original chunk text.
    """
    text = str(prompt or "")
    if not text.strip():
        return []

    chunks: list[str] = []
    current: list[str] = []
    paren_depth = 0
    bracket_depth = 0
    angle_depth = 0

    for char in text:
        if char == "(":
            paren_depth += 1
        elif char == ")" and paren_depth > 0:
            paren_depth -= 1
        elif char == "[":
            bracket_depth += 1
        elif char == "]" and bracket_depth > 0:
            bracket_depth -= 1
        elif char == "<":
            angle_depth += 1
        elif char == ">" and angle_depth > 0:
            angle_depth -= 1

        if char == "," and paren_depth == 0 and bracket_depth == 0 and angle_depth == 0:
            chunk = "".join(current).strip()
            if chunk:
                chunks.append(chunk)
            current = []
            continue

        current.append(char)

    final = "".join(current).strip()
    if final:
        chunks.append(final)
    return chunks


def detect_weight_syntax(chunk: str) -> bool:
    return bool(_WEIGHT_PATTERN.match(str(chunk or "").strip()))


def detect_lora_syntax(chunk: str) -> bool:
    return bool(_LORA_PATTERN.search(str(chunk or "")))
