from __future__ import annotations

from typing import Any


def resource_entry_display(entry: Any) -> str:
    if isinstance(entry, str):
        return entry.strip()
    if isinstance(entry, dict):
        for key in ("title", "display_name", "model_name", "name", "label"):
            value = entry.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""
    for attr in ("display_name", "title", "model_name", "name", "label"):
        value = getattr(entry, attr, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def resource_entry_internal(entry: Any) -> str:
    if isinstance(entry, str):
        return entry.strip()
    if isinstance(entry, dict):
        for key in ("name", "model_name", "title", "label", "display_name"):
            value = entry.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""
    for attr in ("name", "model_name", "title", "label", "display_name"):
        value = getattr(entry, attr, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def normalize_resource_entries(entries: list[Any] | None) -> tuple[list[str], dict[str, str]]:
    values: list[str] = []
    mapping: dict[str, str] = {}
    seen_displays: set[str] = set()
    for entry in entries or []:
        display = resource_entry_display(entry)
        if not display or display in seen_displays:
            continue
        internal = resource_entry_internal(entry) or display
        values.append(display)
        mapping[display] = internal
        seen_displays.add(display)
    return values, mapping
