"""Prompt editor contracts independent of UI toolkit."""

from __future__ import annotations

import re


_TOKEN_PATTERN = re.compile(r"\[\[([^\]]+)\]\]")


PROMPT_TAB_LEFT_COLUMN_MIN_WIDTH = 280
PROMPT_TAB_CENTER_COLUMN_MIN_WIDTH = 560
PROMPT_TAB_RIGHT_COLUMN_MIN_WIDTH = 300
PROMPT_PICKER_COLUMN_MIN_WIDTH = 280
PROMPT_PICKER_ROW_MIN_HEIGHT = 220


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


def get_prompt_tab_column_specs() -> tuple[dict[str, int], ...]:
    return (
        {"index": 0, "weight": 2, "minsize": PROMPT_TAB_LEFT_COLUMN_MIN_WIDTH},
        {"index": 1, "weight": 4, "minsize": PROMPT_TAB_CENTER_COLUMN_MIN_WIDTH},
        {"index": 2, "weight": 2, "minsize": PROMPT_TAB_RIGHT_COLUMN_MIN_WIDTH},
    )
