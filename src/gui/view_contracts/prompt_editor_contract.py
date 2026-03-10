"""Prompt editor contracts independent of UI toolkit."""

from __future__ import annotations

import re


_TOKEN_PATTERN = re.compile(r"\[\[([^\]]+)\]\]")


def build_slot_labels(slot_count: int) -> list[str]:
    count = max(0, int(slot_count))
    return [f"Prompt {i + 1}" for i in range(count)]


def find_undefined_slots(
    *,
    positive_text: str,
    negative_text: str,
    defined_slots: set[str] | list[str],
) -> set[str]:
    known = {str(x) for x in (defined_slots or set())}
    used: set[str] = set()
    for match in _TOKEN_PATTERN.finditer(str(positive_text or "")):
        used.add(match.group(1))
    for match in _TOKEN_PATTERN.finditer(str(negative_text or "")):
        used.add(match.group(1))
    return used - known


def build_editor_warning_text(pack_name: str, dirty: bool, undefined_slots: set[str]) -> str:
    label = f"Editor - {pack_name or 'None'}"
    if dirty:
        label += " (modified)"
    if undefined_slots:
        label += f" | Undefined slots: {', '.join(sorted(undefined_slots))}"
    return label
